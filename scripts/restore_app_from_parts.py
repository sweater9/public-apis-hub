#!/usr/bin/env python3
import base64
from pathlib import Path
root = Path(__file__).resolve().parents[1]
parts = sorted((root/"scripts").glob("_app_b64_*.txt"))
b64 = "".join(p.read_text().strip() for p in parts)
(root/"app.py").write_bytes(base64.b64decode(b64))
print("restored app.py", (root/"app.py").stat().st_size)
