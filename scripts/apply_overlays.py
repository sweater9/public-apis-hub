#!/usr/bin/env python3
"""Decode scripts/overlay_*.tgz.b64 into the app root (used at image build/boot)."""
from __future__ import annotations
import base64, io, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

def main() -> int:
    blobs = sorted(SCRIPTS.glob("overlay_*.tgz.b64"))
    if not blobs:
        print("no overlays found")
        return 0
    for blob in blobs:
        raw = base64.b64decode(blob.read_text().encode("ascii"))
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(ROOT)
        print(f"applied {blob.name} ({len(raw)} bytes)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
