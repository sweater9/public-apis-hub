#!/usr/bin/env python3
"""Parse Cryptocurrency + Blockchain sections from public-apis README into catalog.json."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.request import urlopen

README_URL = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"
WANTED = {"Blockchain", "Cryptocurrency"}
ROW_RE = re.compile(
    r"^\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*(.*?)\s*\|\s*`?([^|`]*?)`?\s*\|\s*(Yes|No)\s*\|\s*(Yes|No|Unknown)\s*\|?\s*$",
    re.M | re.I,
)
SECTION_RE = re.compile(r"^### (.+)$", re.M)


def parse(text: str) -> list[dict]:
    sections = list(SECTION_RE.finditer(text))
    apis: list[dict] = []
    for i, m in enumerate(sections):
        cat = m.group(1).strip()
        if cat not in WANTED:
            continue
        start = m.end()
        end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        body = text[start:end]
        for rm in ROW_RE.finditer(body):
            name, link, desc, auth, https, cors = rm.groups()
            auth = (auth or "").strip() or "No"
            if auth.lower() == "no":
                auth = "No"
            apis.append(
                {
                    "api": name.strip(),
                    "description": desc.strip(),
                    "auth": auth,
                    "https": https.strip(),
                    "cors": cors.strip(),
                    "link": link.strip(),
                    "category": cat,
                }
            )
    return apis


def main() -> int:
    out = Path(__file__).resolve().parent / "catalog.json"
    src = Path(__file__).resolve().parent / "README_source.md"
    if src.exists():
        text = src.read_text(encoding="utf-8")
    else:
        with urlopen(README_URL, timeout=60) as resp:
            text = resp.read().decode("utf-8")
    apis = parse(text)
    out.write_text(json.dumps(apis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(apis)} APIs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
