"""Create a new allowlisted API-only deployment folder. Never deploys or overwrites.

python prepare_staging_bundle.py --destination PATH --snapshot-sha256 REVIEWED_HASH

Only the fixed runtime files and the exact reviewed public-source JSON snapshot
are copied. Local databases, frontend, source stores, tests, logs, credentials and
environment files are not deployment inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from import_snapshot import prepare_snapshot

SOURCE = Path(__file__).resolve().parent
FILES = (
    "backend.py", "import_snapshot.py", "schema_postgres.sql", "requirements.txt",
    "Dockerfile", "railway.toml", ".dockerignore", "data/forward-snapshot.json",
)


def prepare_bundle(destination, expected_snapshot_sha256, *, source=SOURCE):
    if not isinstance(expected_snapshot_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_snapshot_sha256):
        raise ValueError("Provide the exact reviewed snapshot SHA-256.")
    source, destination = Path(source).resolve(), Path(destination).expanduser().resolve()
    if destination.exists() or destination == source or destination.is_relative_to(source):
        raise ValueError("Destination must be a new folder outside the prototype source.")
    contents = {}
    for name in FILES:
        path = source / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("An allowlisted source file is missing or is a symlink.")
        contents[name] = path.read_bytes()
    fingerprint = hashlib.sha256(contents["data/forward-snapshot.json"]).hexdigest()
    if fingerprint != expected_snapshot_sha256.lower():
        raise ValueError("The snapshot changed since review; no bundle was created.")
    _, validated_fingerprint, _, counts = prepare_snapshot(source / "data/forward-snapshot.json")
    if fingerprint != validated_fingerprint:
        raise ValueError("The snapshot changed during validation; no bundle was created.")
    manifest = {
        "version": 1, "purpose": "Private staging API only; no deployment performed",
        "snapshotSHA256": fingerprint, "counts": counts,
        "files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in contents.items()},
    }
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in contents.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (destination / "BUNDLE-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    args = parser.parse_args()
    try:
        manifest = prepare_bundle(args.destination, args.snapshot_sha256)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Bundle preparation failed: {exc}\n")
    print(json.dumps({"destination": str(args.destination.resolve()), "snapshotSHA256": manifest["snapshotSHA256"], "counts": manifest["counts"], "files": len(manifest["files"])}))


if __name__ == "__main__":
    main()
