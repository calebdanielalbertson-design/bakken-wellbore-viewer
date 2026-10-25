import urllib.request,urllib.error,json
base='http://127.0.0.1:58529'
checks={}
checks['empty_search']=json.load(urllib.request.urlopen(base+'/api/wells?q=ZZZ_NO_SUCH_WELL_987654&limit=3'))['total']==0
for header,value in [('Host','attacker.example'),('Origin','https://attacker.example'),('Sec-Fetch-Site','cross-site')]:
    try:
        urllib.request.urlopen(urllib.request.Request(base+'/api/wells/meta',headers={header:value}))
        checks[header]=False
    except urllib.error.HTTPError as error:
        checks[header]=error.code==403
print(json.dumps(checks))
assert all(checks.values())
