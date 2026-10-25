"""Read-only, scoped credential inventory. Never emit secret values."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from well_operations import invoke, TARGET, PROJECT, ENV

DATABASE = '16284981-c662-4d09-938f-c1ec81b1cbe8'

def log_summary(target):
    raw = invoke(['logs', *target, '--latest', '--deployment', '--lines', '100', '--json'])
    entries = []
    health_codes = {}
    failures = 0
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        message = str(item.get('message', ''))
        stamp = item.get('timestamp')
        if stamp:
            entries.append(str(stamp))
        failures += bool(re.search(r'password authentication failed|authentication failed|FATAL.*password', message, re.I))
        match = re.search(r'GET /health HTTP/[\d.]+"?\s+(\d{3})', message)
        if match:
            code = match.group(1)
            health_codes[code] = health_codes.get(code, 0) + 1
    return {'scope': 'last 100 deployment log entries only', 'timestamps_seen': len(entries),
            'earliest_timestamp': min(entries) if entries else None,
            'latest_timestamp': max(entries) if entries else None,
            'health_status_counts': health_codes, 'authentication_failure_messages': failures,
            'not_a_complete_incident_audit': True}

def inventory(target):
    values = json.loads(invoke(['variable', 'list', *target, '--json']))
    user_names = sorted(k for k in values if not k.startswith('RAILWAY_'))
    sensitive_names = [k for k in user_names if any(s in k.upper() for s in ('PASSWORD','SECRET','TOKEN','KEY','DATABASE_URL','DATABASE_PUBLIC_URL'))]
    url = urlsplit(values.get('DATABASE_URL', ''))
    return {
        'variable_names': user_names,
        'potential_secret_variable_names': sensitive_names,
        'database_url_username': url.username,
        'database_url_embeds_password': url.password is not None,
        'private_database_hostname': bool(url.hostname and url.hostname.endswith('.railway.internal')),
        'public_domain_present': bool(values.get('RAILWAY_PUBLIC_DOMAIN')),
        'tcp_proxy_present': bool(values.get('RAILWAY_TCP_PROXY_DOMAIN')),
    }

if __name__ == '__main__':
    report = {'project_id': PROJECT, 'environment_id': ENV, 'operation': 'read-only credential inventory',
              'api': inventory(TARGET),
              'postgres': inventory(['-p', PROJECT, '-e', ENV, '-s', DATABASE]),
              'api_log_summary': log_summary(TARGET),
              'postgres_log_summary': log_summary(['-p', PROJECT, '-e', ENV, '-s', DATABASE]),
              'limitations': ['Not an incident clearance or database integrity audit.', 'No credentials changed.', 'No raw provider logs or secret values persisted.']}
    print(json.dumps(report, indent=2))
