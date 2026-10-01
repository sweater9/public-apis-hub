"""Bootstrap app: restore full app from app_full.b64.part* then expose app."""
from __future__ import annotations

import base64
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"

_parts = sorted(SCRIPTS.glob("app_full.b64.part*"))
if not _parts:
    raise RuntimeError("missing scripts/app_full.b64.part*")
blob = re.sub(r"\s+", "", "".join(p.read_text() for p in _parts))

_restored = ROOT / "_app_restored.py"
_restored.write_bytes(base64.b64decode(blob))
_spec = importlib.util.spec_from_file_location("app_restored", _restored)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
app = _mod.app
