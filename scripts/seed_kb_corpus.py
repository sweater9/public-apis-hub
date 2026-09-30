#!/usr/bin/env python3
"""Write kb/corpus/*.md from embedded offline articles (idempotent)."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "kb" / "corpus"
DATA = json.loads((Path(__file__).with_suffix(".json")).read_text(encoding="utf-8"))

def main() -> int:
    CORPUS.mkdir(parents=True, exist_ok=True)
    n = 0
    for name, content in DATA.items():
        path = CORPUS / name
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        path.write_text(content, encoding="utf-8")
        n += 1
    print(f"Seeded {n} files ({len(DATA)} total) → {CORPUS}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
