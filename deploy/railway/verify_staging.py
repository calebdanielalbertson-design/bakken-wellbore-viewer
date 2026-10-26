"""Read-only cloud verification with strictly allowlisted output (no secrets)."""
import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import workspace_paths as wp
ROOT = wp.REPO
CLI = wp.railway_cli()
TARGET = ["-p", "e2cc4cb2-b22f-4ea4-99ed-329befa4cf60", "-e", "78d48523-3b40-4010-8d4f-10c04d69fe23", "-s", "f73fc3a9-e7ce-451f-a985-e46e08040ba0"]

def read(args):
    result = subprocess.run([str(CLI), *args], text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise SystemExit("Read-only Railway check failed; provider output withheld")
    return json.loads(result.stdout)

variables = read(["variable", "list", *TARGET, "--json"])
parsed = urlsplit(variables.get("DATABASE_URL", ""))
checks = {
    "ownerImportReferenceAbsent": "BAKKEN_IMPORT_DATABASE_URL" not in variables,
    "readerUsername": parsed.username == "forward_reader",
    "passwordAbsentFromURL": parsed.password is None,
    "readerPasswordConfigured": bool(variables.get("PGPASSWORD")),
    "databaseHostIsPrivate": bool(parsed.hostname and parsed.hostname.endswith(".railway.internal")),
    "databaseTLSRequired": parse_qs(parsed.query).get("sslmode") == ["require"],
    "corsOriginsEmpty": not variables.get("BAKKEN_ALLOWED_ORIGINS"),
    "apiPublicDomainAbsent": not variables.get("RAILWAY_PUBLIC_DOMAIN"),
    "apiTCPProxyAbsent": not variables.get("RAILWAY_TCP_PROXY_DOMAIN"),
}
variables = None
deployments = read(["deployment", "list", *TARGET, "--limit", "1", "--json"])
latest = deployments[0]
result = {"environment": "staging", "checks": checks,
          "deployment": {k: latest.get(k) for k in ("id", "status", "createdAt")}}
print(json.dumps(result, indent=2))
if not all(checks.values()) or latest.get("status") != "SUCCESS":
    raise SystemExit(1)
