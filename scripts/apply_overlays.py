#!/usr/bin/env python3
"""Decode scripts/overlay_*.tgz.b64 into the app root (used at image build/boot)."""
from __future__ import annotations
import base64, binascii, io, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

def _materialize_splits() -> None:
    parts = sorted(SCRIPTS.glob("overlay_*.tgz.b64.part*"))
    groups: dict[str, list[Path]] = {}
    for p in parts:
        name = p.name.split(".part")[0]
        groups.setdefault(name, []).append(p)
    for name, plist in groups.items():
        plist = sorted(plist)
        out = SCRIPTS / name
        out.write_text("".join(x.read_text().strip() for x in plist) + "\n")
        print(f"joined {name} from {len(plist)} parts")

def main() -> int:
    _materialize_splits()
    blobs = sorted(SCRIPTS.glob("overlay_*.tgz.b64"))
    if not blobs:
        print("no overlays found")
        return 0
    for blob in blobs:
        text = blob.read_text().strip()
        if not text or text == "PLACEHOLDER":
            print(f"skip {blob.name}: empty placeholder")
            continue
        try:
            raw = base64.b64decode(text.encode("ascii"), validate=True)
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
                tar.extractall(ROOT)
        except (binascii.Error, tarfile.TarError, ValueError) as exc:
            print(f"skip {blob.name}: {exc}")
            continue
        print(f"applied {blob.name} ({len(raw)} bytes)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
