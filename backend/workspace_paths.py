"""Repository-relative locations shared by backend and deploy scripts.

Defaults follow the repository layout (backend/, explorer/, site/). Each
location can be overridden with an environment variable, so a checkout with
data stored elsewhere still works without editing code.

    BAKKEN_EXPLORER_DIR  explorer folder holding full-dataset/ (default: explorer/)
    BAKKEN_SITE_DIST     public site build served locally (default: site/dist/)
    BAKKEN_WORK_DIR      scratch area for refresh runs and deploy bundles (default: work/, git-ignored)
    RAILWAY_CLI          Railway CLI executable (default: `railway` on PATH)
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


EXPLORER = _env_path('BAKKEN_EXPLORER_DIR', REPO / 'explorer')
FULL_DATASET = EXPLORER / 'full-dataset'
SITE_DIST = _env_path('BAKKEN_SITE_DIST', REPO / 'site' / 'dist')
WORK = _env_path('BAKKEN_WORK_DIR', REPO / 'work')
BACKEND = REPO / 'backend'


def railway_cli() -> str:
    """Railway CLI to invoke: $RAILWAY_CLI, else `railway` found on PATH."""
    return os.environ.get('RAILWAY_CLI') or shutil.which('railway') or 'railway'
