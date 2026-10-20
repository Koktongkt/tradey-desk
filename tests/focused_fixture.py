"""Offline search transport envelope; production manifest/parser remain real."""
import datetime as dt
import json
import subprocess
from focused_search import SearchReceipt


def search_done(manifest=None, *, attested=()):
    done=subprocess.CompletedProcess([],0,json.dumps(manifest or {'candidates':[]}).encode(),b'')
    done.private_artifact=SearchReceipt(set(attested),dt.datetime.now(dt.timezone.utc).isoformat())
    return done


def validation_done(urls, **kwargs):
    return {'version':2,'status':'ok','results':[
        {'requested_url':u,'eligible':True,'reason':'success'} for u in urls]}


def extraction_miss(urls, **kwargs):
    return {'version':2,'status':'error','reason':'timeout'}
