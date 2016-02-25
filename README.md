An OpenRefine reconciliation service for [ISNI](http://isni.org).

The service queries the [ISNI SRU API](http://isni.oclc.nl/sru/?version=1.1)
and provides normalized scores across queries for reconciling in Refine.

Run locally as:
~~~~
$ python reconcile.py --debug
~~~~

Add the service by entering the URL 'http://0.0.0.0:5000/reconcile'.

Michael Stephens wrote a [demo reconcilliation service](https://github.com/mikejs/reconcile-demo) that this code is based on.

Tested on python 2.7.10 and 3.4.3
