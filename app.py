"""Bootstrap app: restore full app.py from scripts/_app_b64_*.txt then expose app."""
from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = sorted((ROOT / "scripts").glob("_app_b64_*.txt"))

if not PARTS:
    raise RuntimeError("missing scripts/_app_b64_*.txt restore parts")

_restored = ROOT / "_app_restored.py"
_restored.write_bytes(base64.b64decode("".join(p.read_text().strip() for p in PARTS)))
_spec = importlib.util.spec_from_file_location("app_restored", _restored)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
app = _mod.app
