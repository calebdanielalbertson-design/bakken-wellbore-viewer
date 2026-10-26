"""Pack, upload and fetch the prepared datasets that are too large for Git.

Each dataset in datasets.json is one folder in the repo (for example
explorer/full-dataset). It is stored in a private S3-compatible bucket as a
single versioned archive whose SHA-256 is recorded in datasets.json, so a
fresh clone can download exactly the data the code was tested with.

    python scripts/datasets.py status                  # what is present locally
    python scripts/datasets.py fetch                   # download + verify every dataset
    python scripts/datasets.py fetch explorer-full-dataset
    python scripts/datasets.py pack site-viewer-data --version 2026-10-17
    python scripts/datasets.py push site-viewer-data   # upload the packed archive

Bucket access comes only from environment variables, never from files in Git:

    BAKKEN_DATA_BUCKET       bucket name
    BAKKEN_DATA_ENDPOINT     S3 endpoint URL (Cloudflare R2: https://<account-id>.r2.cloudflarestorage.com;
                             omit for AWS S3)
    AWS_ACCESS_KEY_ID        access key (read-only keys are enough for fetch)
    AWS_SECRET_ACCESS_KEY
    AWS_REGION               optional; defaults to "auto" (correct for R2)

status and pack need only the Python standard library. fetch and push need
boto3:  pip install -r scripts/requirements-data.txt
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / 'datasets.json'
ARCHIVES = REPO / 'work' / 'datasets'
KEY_PREFIX = 'datasets'
CHUNK = 1024 * 1024


class DataError(Exception):
    """A problem the person running the command needs to fix."""


# ---------------------------------------------------------------- manifest

def load_manifest(path: Path = MANIFEST) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('datasets'), dict):
        raise DataError(f'{path.name} is not a version 1 dataset manifest')
    return data


def save_manifest(data: dict, path: Path = MANIFEST) -> None:
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def dataset(data: dict, name: str) -> dict:
    try:
        return data['datasets'][name]
    except KeyError:
        known = ', '.join(sorted(data['datasets']))
        raise DataError(f'Unknown dataset {name!r}. Known datasets: {known}') from None


def target_dir(entry: dict, repo: Path = REPO) -> Path:
    path = (repo / entry['path']).resolve()
    if not path.is_relative_to(repo.resolve()):
        raise DataError(f"Dataset path {entry['path']!r} leaves the repository")
    return path


def object_key(name: str, version: str) -> str:
    return f'{KEY_PREFIX}/{name}/{version}/{name}.tar.gz'


def archive_path(name: str, version: str, archives: Path = ARCHIVES) -> Path:
    return archives / f'{name}-{version}.tar.gz'


# ---------------------------------------------------------------- files

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def included_files(folder: Path, exclude: list[str]) -> list[Path]:
    """Files to pack, sorted for a stable archive. Code and caches stay in Git or out entirely."""
    files = []
    for path in sorted(folder.rglob('*')):
        rel = path.relative_to(folder)
        if not path.is_file() or path.is_symlink():
            continue
        if '__pycache__' in rel.parts or any(rel.match(pattern) for pattern in exclude):
            continue
        files.append(path)
    return files


def pack(name: str, version: str, *, data: dict, repo: Path = REPO, archives: Path = ARCHIVES) -> dict:
    entry = dataset(data, name)
    folder = target_dir(entry, repo)
    if not folder.is_dir():
        raise DataError(f"{entry['path']} does not exist; nothing to pack")
    files = included_files(folder, entry.get('exclude', []))
    if not files:
        raise DataError(f"{entry['path']} has no files to pack")
    archives.mkdir(parents=True, exist_ok=True)
    out = archive_path(name, version, archives)
    if out.exists():
        raise DataError(f'{out} already exists; choose a new --version or remove the old archive')

    def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
        # Reproducible metadata: no owner names, fixed modes.
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        info.mode = 0o644
        return info

    partial = out.with_suffix('.partial')
    with tarfile.open(partial, 'w:gz', compresslevel=6) as tar:
        for path in files:
            tar.add(path, arcname=path.relative_to(folder).as_posix(), recursive=False, filter=normalize)
    partial.replace(out)
    entry.update({'version': version, 'key': object_key(name, version), 'sha256': sha256_file(out),
                  'bytes': out.stat().st_size, 'files': len(files),
                  'contentBytes': sum(p.stat().st_size for p in files)})
    return entry


def extract(archive: Path, destination: Path, *, expected_files: int | None = None, force: bool = False,
            exclude: tuple[str, ...] | list[str] = ()) -> int:
    """Extract into destination via a temporary sibling folder, so a failure never leaves half a dataset.

    Files matching `exclude` (code tracked in Git beside the data) are kept as they are.
    """
    if destination.is_dir() and included_files(destination, list(exclude)) and not force:
        raise DataError(f'{destination} already has files; use --force to replace them')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.fetch-', dir=destination.parent))
    try:
        with tarfile.open(archive, 'r:gz') as tar:
            members = tar.getmembers()
            for member in members:
                target = (staging / member.name).resolve()
                if not target.is_relative_to(staging.resolve()) or not (member.isfile() or member.isdir()):
                    raise DataError(f'Unsafe archive entry refused: {member.name}')
            tar.extractall(staging, filter='data')
        count = len(included_files(staging, list(exclude)))
        if expected_files is not None and count != expected_files:
            raise DataError(f'Archive held {count} files; datasets.json expects {expected_files}')
        if destination.exists():
            for path in destination.rglob('*'):  # keep tracked code that lives beside the data
                rel = path.relative_to(destination)
                if path.is_file() and '__pycache__' not in rel.parts and any(rel.match(x) for x in exclude):
                    (staging / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, staging / rel)
            shutil.rmtree(destination)
        staging.rename(destination)
        return count
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------- bucket

def bucket_client():
    bucket = os.environ.get('BAKKEN_DATA_BUCKET')
    if not bucket:
        raise DataError('Set BAKKEN_DATA_BUCKET (and BAKKEN_DATA_ENDPOINT for Cloudflare R2) first')
    if not (os.environ.get('AWS_ACCESS_KEY_ID') and os.environ.get('AWS_SECRET_ACCESS_KEY')):
        raise DataError('Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY for the data bucket first')
    try:
        import boto3
    except ImportError:
        raise DataError('boto3 is needed: pip install -r scripts/requirements-data.txt') from None
    client = boto3.client('s3', endpoint_url=os.environ.get('BAKKEN_DATA_ENDPOINT') or None,
                          region_name=os.environ.get('AWS_REGION', 'auto'))
    return client, bucket


def remote_sha(client, bucket: str, key: str) -> str | None:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception as error:  # botocore ClientError; 404 means absent
        code = getattr(error, 'response', {}).get('Error', {}).get('Code')
        if code in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise
    return head.get('Metadata', {}).get('sha256')


def push(name: str, *, data: dict, client, bucket: str, archives: Path = ARCHIVES) -> str:
    entry = dataset(data, name)
    if not entry.get('sha256'):
        raise DataError(f'{name} has not been packed yet; run pack first')
    archive = archive_path(name, entry['version'], archives)
    if not archive.is_file() or sha256_file(archive) != entry['sha256']:
        raise DataError(f'{archive} is missing or does not match datasets.json; pack it again')
    existing = remote_sha(client, bucket, entry['key'])
    if existing == entry['sha256']:
        return 'already uploaded'
    if existing is not None:
        raise DataError(f"{entry['key']} already exists with different contents; versions are never overwritten. "
                        'Pack with a new --version instead.')
    client.upload_file(str(archive), bucket, entry['key'],
                       ExtraArgs={'Metadata': {'sha256': entry['sha256']}, 'ContentType': 'application/gzip'})
    if remote_sha(client, bucket, entry['key']) != entry['sha256']:
        raise DataError(f"Upload of {entry['key']} could not be confirmed")
    return 'uploaded'


def fetch(name: str, *, data: dict, client, bucket: str, repo: Path = REPO, force: bool = False) -> int:
    entry = dataset(data, name)
    if not entry.get('sha256'):
        raise DataError(f'{name} has no published version yet')
    destination = target_dir(entry, repo)
    with tempfile.TemporaryDirectory() as temp:
        download = Path(temp) / 'download.tar.gz'
        client.download_file(bucket, entry['key'], str(download))
        actual = sha256_file(download)
        if actual != entry['sha256']:
            raise DataError(f"Checksum mismatch for {name}: expected {entry['sha256']}, got {actual}. Nothing was changed.")
        return extract(download, destination, expected_files=entry.get('files'), force=force,
                       exclude=entry.get('exclude', []))


def status(data: dict, repo: Path = REPO) -> list[tuple[str, str, str]]:
    rows = []
    for name, entry in sorted(data['datasets'].items()):
        folder = target_dir(entry, repo)
        have = len(included_files(folder, entry.get('exclude', []))) if folder.is_dir() else 0
        expected = entry.get('files')
        if not entry.get('sha256'):
            state = f'not published yet ({have} files local)'
        elif have == 0:
            state = 'missing - run: python scripts/datasets.py fetch ' + name
        elif expected is not None and have != expected:
            state = f'present but {have} files (expected {expected})'
        else:
            state = f'present ({have} files)'
        rows.append((name, entry.get('version') or '-', state))
    return rows


# ---------------------------------------------------------------- command line

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='show which datasets are present locally')
    f = sub.add_parser('fetch', help='download and verify datasets (all by default)')
    f.add_argument('names', nargs='*')
    f.add_argument('--force', action='store_true', help='replace a dataset folder that already has files')
    p = sub.add_parser('pack', help='build a versioned archive and record it in datasets.json')
    p.add_argument('name')
    p.add_argument('--version', required=True, help='data version, e.g. the DMR source date 2026-10-17')
    u = sub.add_parser('push', help='upload packed archives to the bucket (never overwrites)')
    u.add_argument('names', nargs='+')
    args = parser.parse_args(argv)

    try:
        data = load_manifest()
        if args.command == 'status':
            for name, version, state in status(data):
                print(f'{name:<24} {version:<12} {state}')
        elif args.command == 'pack':
            entry = pack(args.name, args.version, data=data)
            save_manifest(data)
            print(f"packed {args.name} {entry['version']}: {entry['files']} files, "
                  f"{entry['bytes'] / 1e6:.1f} MB, sha256 {entry['sha256'][:12]}")
            print('Commit datasets.json, then run: python scripts/datasets.py push ' + args.name)
        elif args.command == 'push':
            client, bucket = bucket_client()
            for name in args.names:
                print(f'{name}: ' + push(name, data=data, client=client, bucket=bucket))
        elif args.command == 'fetch':
            client, bucket = bucket_client()
            for name in args.names or sorted(data['datasets']):
                if not dataset(data, name).get('sha256'):
                    print(f'{name}: skipped (not published yet)')
                    continue
                count = fetch(name, data=data, client=client, bucket=bucket, force=args.force)
                print(f'{name}: {count} files verified and installed')
    except DataError as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
