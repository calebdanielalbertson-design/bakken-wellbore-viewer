"""One-time private staging import entrypoint; remove hook and owner afterward."""
import json,os
from pathlib import Path
from wells_store import import_postgres
from verify_wells import verify

if __name__=='__main__':
    if os.environ.get('RAILWAY_ENVIRONMENT_NAME')!='staging':
        raise SystemExit('Refusing import outside staging.')
    url=os.environ.get('BAKKEN_IMPORT_DATABASE_URL','')
    if not url: raise SystemExit('Separate temporary importer connection required.')
    try:
        imported=import_postgres(Path('data/well-release'),url,initialize=True,grant_reader=True)
        verified=verify()
    except Exception:
        raise SystemExit('Staging well import/verification failed; provider output withheld.')
    print(json.dumps({'imported':imported,'verification':verified},separators=(',',':')),flush=True)
