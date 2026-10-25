"""Explicit one-time Railway staging variables; credentials never leave memory.

This operations helper is NOT part of the deployment bundle. It creates only
the new database reader password, uses CLI stdin, and never prints CLI output.
"""
from pathlib import Path
import json
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "work/railway-tools/node_modules/@railway/cli/bin/railway.exe"
PROJECT = "e2cc4cb2-b22f-4ea4-99ed-329befa4cf60"
ENVIRONMENT = "78d48523-3b40-4010-8d4f-10c04d69fe23"
SERVICE = "f73fc3a9-e7ce-451f-a985-e46e08040ba0"
TARGET = ["-p", PROJECT, "-e", ENVIRONMENT, "-s", SERVICE]


def invoke(args, value=None):
    result = subprocess.run([str(CLI), *args], input=value, text=True,
                            capture_output=True, timeout=60)
    if result.returncode:
        # Do not expose command arguments, process environment or provider output.
        raise RuntimeError("Railway operation failed; no credential output retained")
    return result.stdout


if sys.argv[1:] != ["--configure-new-staging-api"]:
    raise SystemExit("Explicit --configure-new-staging-api is required")
current = json.loads(invoke(["variable", "list", *TARGET, "--json"]))
if "PGPASSWORD" in current:
    raise SystemExit("Reader secret already exists; refusing implicit rotation")
reader_password = secrets.token_urlsafe(48)
invoke(["variable", "set", *TARGET, "--stdin", "--skip-deploys", "PGPASSWORD"], reader_password)
reader_password = None
invoke(["variable", "set", *TARGET, "--skip-deploys",
        "DATABASE_URL=postgresql://forward_reader@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}?sslmode=require",
        "BAKKEN_IMPORT_DATABASE_URL=${{Postgres.DATABASE_URL}}",
        "BAKKEN_ALLOWED_ORIGINS="])
print(json.dumps({"configured": True, "environment": "staging",
                  "service": SERVICE, "readerSecret": "stored in Railway via stdin",
                  "importOwnerReference": "temporary; remove after bootstrap"}))
