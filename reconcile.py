"""
An OpenRefine reconciliation service for the API provided by
OCLC for FAST.

See API documentation:
http://www.oclc.org/developer/documentation/fast-linked-data-api/request-types

This code is adapted from Michael Stephens:
https://github.com/mikejs/reconcile-demo
"""
from flask import Flask
from flask import request
from flask import jsonify
import json

from lxml import etree
from operator import itemgetter
from sys import version_info

#For scoring results
from fuzzywuzzy import fuzz
import requests

app = Flask(__name__)

#some config
api_base_url = 'http://isni.oclc.nl/sru/?operation=searchRetrieve&recordSchema=isni-b&query='

#See if Python 3 for unicode/str use decisions
PY3 = version_info > (3,)

if PY3:
    import urllib.parse
else:
    import urllib

#If it's installed, use the requests_cache library to
#cache calls to the FAST API.
try:
    import requests_cache
    requests_cache.install_cache('isni_cache')
except ImportError:
    app.logger.debug("No request cache found.")
    pass

#Helper text processing
import text

#Map the FAST query indexes to service types
default_query = {
    "id": "/isni/name",
    "name": "Name",
    "index": "pica.na"
}

refine_to_isni = [
    {
        "id": "/isni/name_keyword",
        "name": "Name Keyword",
        "index": "pica.nw"
    },
    {
        "id": "/isni/any_phrase",
        "name": "Any Phrase",
        "index": "pica.aph"
    },
    {
        "id": "/isni/isni_number",
        "name": "ISNI Number",
        "index": "pica.isn"
    }
]
refine_to_isni.append(default_query)


#Make a copy of the FAST mappings.
#Minus the index for
query_types = [{'id': item['id'], 'name': item['name']} for item in refine_to_isni]

# Basic service metadata. There are a number of other documented options
# but this is all we need for a simple service.
metadata = {
    "name": "ISNI Reconciliation Service",
    "defaultTypes": query_types,
    "view": {
        "url": "{{id}}"
    }
}


def jsonpify(obj):
    """
    Helper to support JSONP
    """
    try:
        callback = request.args['callback']
        response = app.make_response("%s(%s)" % (callback, json.dumps(obj)))
        response.mimetype = "text/javascript"
        return response
    except KeyError:
        return jsonify(obj)


def search(raw_query, query_type='/isni/name'):
    """
    Hit the ISNI API for names.
    """
    out = []
    unique_isni_ids = []
    query = text.normalize(raw_query, PY3).strip().replace(',', '')
    query_type_meta = [i for i in refine_to_isni if i['id'] == query_type]
    if query_type_meta == []:
        query_type_meta = default_query
    query_index = query_type_meta[0]['index']
    try:
        #ISNI api requires spaces to be encoded as %20 rather than +
        if PY3:
            url = api_base_url + query_index + "+%3D+'" + urllib.parse.quote(query) +"'"
        else:
            url = api_base_url + query_index + "+%3D+'" + urllib.quote(query) + "'"
        app.logger.debug("ISNI API url is " + url)
        resp = requests.get(url)
        results = etree.fromstring(resp.content)
    except Exception as e:
        app.logger.warning(e)
        return out
    for record in results.iter("{http://www.loc.gov/zing/srw/}record"):
        match = False
        names = []
        if record.xpath(".//personalName"):
            for pers in record.xpath(".//personalName"):
                try:
                    fname = pers.find("forename").text
                except:
                    fname = ''
                lname = pers.find("surname").text
                try:
                    date = pers.find("dates").text
                except:
                    date = ''
                name = str(fname) + " " + lname + ' ' + str(date)
                names.append(name.strip(''))
            refine_name = names[0]
        elif record.xpath(".//organisation"):
            for org in record.xpath(".//organisationName"):
                mainname = org.find("mainName").text
                try:
                    subname = org.find("subdivisionName").text
                except:
                    subname = ''
                name = mainname + ' ' + str(subname)
                name.strip('')
                names.append(name)
            refine_name = names[0]
        isni_uri = record.xpath(".//isniURI")[0].text
        if isni_uri in unique_isni_ids:
            continue
        else:
            unique_isni_ids.append(isni_uri)
        scores = set()
        app.logger.debug(names)
        for name in names:
            nscore = fuzz.token_sort_ratio(query, name)
            scores.add(nscore)
        score = max(scores)
        for name in names:
            if query == text.normalize(name, PY3):
                match = True
        resource = {
            "id": isni_uri,
            "name": refine_name,
            "score": score,
            "match": match,
            "type": query_type_meta
        }
        out.append(resource)
    #Sort this list by score
    sorted_out = sorted(out, key=itemgetter('score'), reverse=True)
    #Refine only will handle top three matches.
    return sorted_out[:3]


@app.route("/reconcile", methods=['POST', 'GET'])
def reconcile():
    #Single queries have been deprecated.  This can be removed.
    #Look first for form-param requests.
    query = request.form.get('query')
    if query is None:
        #Then normal get param.s
        query = request.args.get('query')
        query_type = request.args.get('type', '/isni/name')
    if query:
        # If the 'query' param starts with a "{" then it is a JSON object
        # with the search string as the 'query' member. Otherwise,
        # the 'query' param is the search string itself.
        if query.startswith("{"):
            query = json.loads(query)['query']
        results = search(query, query_type=query_type)
        return jsonpify({"result": results})
    # If a 'queries' parameter is supplied then it is a dictionary
    # of (key, query) pairs representing a batch of queries. We
    # should return a dictionary of (key, results) pairs.
    queries = request.form.get('queries')
    if queries:
        queries = json.loads(queries)
        results = {}
        for (key, query) in queries.items():
            qtype = query.get('type')
            #If no type is specified this is likely to be the initial query
            #so lets return the service metadata so users can choose what
            #FAST index to use.
            if qtype is None:
                return jsonpify(metadata)
            data = search(query['query'], query_type=qtype)
            results[key] = {"result": data}
        return jsonpify(results)
    # If neither a 'query' nor 'queries' parameter is supplied then
    # we should return the service metadata.
    return jsonpify(metadata)

if __name__ == '__main__':
    from optparse import OptionParser
    oparser = OptionParser()
    oparser.add_option('-d', '--debug', action='store_true', default=False)
    opts, args = oparser.parse_args()
    app.debug = opts.debug
    app.run(host='0.0.0.0')
