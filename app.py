"""Bootstrap app: restore full app from b64 parts or app_full.b64 then expose app."""
from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"

# Prefer split app_full.b64.partNN, then app_full.b64, then legacy _app_b64_*.txt
_parts = sorted(SCRIPTS.glob("app_full.b64.part*"))
if _parts:
    blob = "".join(p.read_text().strip() for p in _parts)
elif (SCRIPTS / "app_full.b64").is_file():
    blob = (SCRIPTS / "app_full.b64").read_text().strip()
else:
    legacy = sorted(SCRIPTS.glob("_app_b64_*.txt"))
    if not legacy:
        raise RuntimeError("missing app restore blobs under scripts/")
    blob = "".join(p.read_text().strip() for p in legacy)

_restored = ROOT / "_app_restored.py"
_restored.write_bytes(base64.b64decode(blob))
_spec = importlib.util.spec_from_file_location("app_restored", _restored)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
app = _mod.app
