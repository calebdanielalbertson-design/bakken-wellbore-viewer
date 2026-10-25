"""Scoped staging operations. No token/config/secret output is retained.

Uses the already-authorized Railway CLI session; never creates SSH keys/domains.
"""
from pathlib import Path
import argparse,json,subprocess,sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
CLI=ROOT/'work/railway-tools/node_modules/@railway/cli/bin/railway.exe'
PROJECT='e2cc4cb2-b22f-4ea4-99ed-329befa4cf60'
ENV='78d48523-3b40-4010-8d4f-10c04d69fe23'
SERVICE='f73fc3a9-e7ce-451f-a985-e46e08040ba0'
TARGET=['-p',PROJECT,'-e',ENV,'-s',SERVICE]


def invoke(args,stdin=None,timeout=60):
    result=subprocess.run([str(CLI),*args],input=stdin,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=timeout)
    if result.returncode: raise RuntimeError('Scoped Railway command failed; provider output withheld.')
    return result.stdout


def graphql(document,variables=None):
    args=['api',document,'--compact']
    if variables is not None: args+=['--variables',json.dumps(variables,separators=(',',':'))]
    result=json.loads(invoke(args))
    if result.get('errors'): raise RuntimeError('Railway API rejected the scoped operation; response withheld.')
    return result.get('data',result)


def probe():
    query='query($project:String!,$service:String!,$environment:String!){project(id:$project){id name environments{edges{node{id name serviceInstances{edges{node{serviceId}}}}}}} serviceInstance(serviceId:$service,environmentId:$environment){serviceId environmentId preDeployCommand preDeployTimeoutSeconds startCommand healthcheckPath latestDeployment{id status createdAt}}}'
    result=graphql(query,{'project':PROJECT,'service':SERVICE,'environment':ENV})
    project=result['project'];instance=result['serviceInstance']
    if project['id']!=PROJECT or instance['serviceId']!=SERVICE or instance['environmentId']!=ENV:
        raise RuntimeError('Unexpected Railway target.')
    environments=[edge['node'] for edge in project['environments']['edges']]
    staging=[item for item in environments if item['id']==ENV]
    if len(staging)!=1 or staging[0]['name']!='staging': raise RuntimeError('Expected staging environment absent.')
    for item in environments:
        if item['id']!=ENV and any(edge['node']['serviceId']==SERVICE for edge in item['serviceInstances']['edges']):
            raise RuntimeError('API has another environment instance; refusing cross-environment settings mutation.')
    variables=json.loads(invoke(['variable','list',*TARGET,'--json']))
    reader=urlsplit(variables.get('DATABASE_URL',''))
    if (reader.username!='forward_reader' or not reader.hostname or not reader.hostname.endswith('.railway.internal')
            or reader.password is not None or not variables.get('PGPASSWORD')
            or variables.get('RAILWAY_TCP_PROXY_DOMAIN')):
        raise RuntimeError('Private restricted-reader configuration changed.')
    public_api=bool(variables.get('RAILWAY_PUBLIC_DOMAIN'))
    if public_api and (len(variables.get('BAKKEN_PREVIEW_TOKEN',''))<40 or 'staging_gateway:application' not in (instance['startCommand'] or '')):
        raise RuntimeError('Public staging endpoint lacks the expected protected gateway.')
    checks={'private_reader':True,'owner_reference_present':'BAKKEN_IMPORT_DATABASE_URL' in variables,
            'well_health_required':variables.get('BAKKEN_REQUIRE_WELL_RELEASE')=='1',
            'no_public_origin':not variables.get('BAKKEN_ALLOWED_ORIGINS'),
            'authenticated_preview_endpoint':public_api}
    variables=None
    database_variables=json.loads(invoke(['variable','list','-p',PROJECT,'-e',ENV,'-s','16284981-c662-4d09-938f-c1ec81b1cbe8','--json']))
    checks['database_public_domain_absent']=not database_variables.get('RAILWAY_PUBLIC_DOMAIN')
    checks['database_tcp_proxy_absent']=not database_variables.get('RAILWAY_TCP_PROXY_DOMAIN')
    database_variables=None
    return {'project':project['name'],'environments':[{'id':e['id'],'name':e['name'],'service_count':len(e['serviceInstances']['edges'])} for e in environments],
            'instance':instance,'checks':checks}


def set_hook(command):
    return graphql('mutation($service:String!,$environment:String!,$input:ServiceInstanceUpdateInput!){serviceInstanceUpdate(serviceId:$service,environmentId:$environment,input:$input)}',
                   {'service':SERVICE,'environment':ENV,'input':{'preDeployCommand':[command] if command else [],'preDeployTimeoutSeconds':1800,'healthcheckPath':'/health'}})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['probe','prepare-import','clear-import','deploy','status','logs','build-progress','reader-check-start','normal-start','redeploy'])
    parser.add_argument('--bundle',type=Path)
    args=parser.parse_args()
    try:
        if args.operation=='probe': result=probe()
        elif args.operation=='prepare-import':
            state=probe()
            if state['checks']['owner_reference_present']: raise ValueError('An importer owner reference already exists; inspect it first.')
            # Placeholder reference is resolved only in Railway, not on this machine.
            invoke(['variable','set',*TARGET,'--skip-deploys','BAKKEN_IMPORT_DATABASE_URL=${{Postgres.DATABASE_URL}}','BAKKEN_REQUIRE_WELL_RELEASE=1'])
            set_hook('python staging_well_import.py')
            result={'prepared':True,'environment':'staging','temporary_import_hook':True}
        elif args.operation=='clear-import':
            state=probe()
            set_hook(None)
            if state['checks']['owner_reference_present']:
                invoke(['variable','delete',*TARGET,'BAKKEN_IMPORT_DATABASE_URL'])
            result={'cleared':True,'environment':'staging','owner_reference_present':False}
        elif args.operation in {'reader-check-start','normal-start'}:
            probe()
            command="sh -c '"+('python verify_wells.py && ' if args.operation=='reader-check-start' else '')+"exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 30 --access-logfile - backend:application'"
            graphql('mutation($service:String!,$environment:String!,$input:ServiceInstanceUpdateInput!){serviceInstanceUpdate(serviceId:$service,environmentId:$environment,input:$input)}',
                {'service':SERVICE,'environment':ENV,'input':{'startCommand':command}})
            result={'reader_check_at_start':args.operation=='reader-check-start','environment':'staging'}
        elif args.operation=='redeploy':
            state=probe()
            if state['checks']['owner_reference_present'] or state['instance']['preDeployCommand']:
                raise ValueError('Remove the temporary importer before stable redeployment.')
            value=json.loads(invoke(['redeploy',*TARGET,'--yes','--json']))
            result={'redeployed':True,'environment':'staging',**{k:v for k,v in value.items() if k in {'id','deploymentId','status'}}}
        elif args.operation=='deploy':
            probe()
            target=args.bundle.resolve() if args.bundle else None
            allowed=ROOT/'work/connected-wells-deploy'
            if not target or not target.is_dir() or not target.is_relative_to(allowed.resolve()) or not (target/'BUNDLE-MANIFEST.json').is_file():
                raise ValueError('Expected an allowlisted staging bundle beneath work/connected-wells-deploy.')
            output=invoke(['up',str(target),'--path-as-root',*TARGET,'--detach','--json','--message','Connected well profiles, staging only'],timeout=180)
            # CLI deployment output has only IDs, URLs and build progress. Return
            # recognized IDs/status only, never arbitrary provider output.
            parsed=[]
            for line in output.splitlines():
                try:item=json.loads(line)
                except ValueError:continue
                if isinstance(item,dict): parsed.append({key:value for key,value in item.items() if key in {'deploymentId','id','status','projectId','serviceId','environmentId'}})
            result={'uploaded':True,'environment':'staging','provider':parsed}
        elif args.operation=='status':
            rows=json.loads(invoke(['deployment','list',*TARGET,'--limit','3','--json']))
            result=[{key:row.get(key) for key in ('id','status','createdAt')} for row in rows]
        elif args.operation=='build-progress':
            output=invoke(['logs',*TARGET,'--latest','--build','--lines','30','--json'])
            result=[]
            for line in output.splitlines():
                try:item=json.loads(line); message=item.get('message','')
                except ValueError:continue
                # Fixed Dockerfile has no ENV secrets and these build log lines
                # are restricted to dependency/build phase names.
                if any(word in message for word in ['COPY','exporting','Successfully installed','ERROR:','CACHED','collecting','Collecting','load build','Starting','python:3.12','RUN pip','useradd','DONE']):
                    result.append({'time':item.get('timestamp'),'phase':message[:400]})
        else:
            output=invoke(['logs',*TARGET,'--latest','--deployment','--lines','100','--json'])
            # Only our verifier's parseable JSON payload is admitted.
            result=[]
            for line in output.splitlines():
                try:
                    log=json.loads(line)
                    # Railway promotes structured JSON stdout into log fields.
                    if log.get('verified') is True:
                        item={k:v for k,v in log.items() if k in {'verified','environment','release_id','counts','production','reader','read_only','checks','sample_checks','forward_counts','timestamp'}}
                    elif isinstance(log.get('verification'),dict):
                        item={k:v for k,v in log.items() if k in {'imported','verification','timestamp'}}
                    else:
                        item=json.loads(log.get('message',''))
                except (ValueError,AttributeError,TypeError):continue
                if isinstance(item,dict) and ('verification' in item or item.get('verified') is True): result.append(item)
            if result:
                (ROOT/'work/bakken-forward-preview/railway-wells-reader-verification.json').write_text(json.dumps(result[-1],indent=2))
    except Exception:
        raise SystemExit('Scoped staging operation failed; credentials/provider output withheld.')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
