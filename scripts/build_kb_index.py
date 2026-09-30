#!/usr/bin/env python3
"""Build SQLite FTS5 index from kb/corpus/*.md → data/kb.sqlite"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "kb" / "corpus"
DB_PATH = ROOT / "data" / "kb.sqlite"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta_raw, body = m.group(1), m.group(2)
    meta: dict = {}
    for line in meta_raw.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            tags = []
            for part in inner.split(","):
                part = part.strip().strip('"').strip("'")
                if part:
                    tags.append(part)
            meta[key] = tags
        else:
            meta[key] = val.strip('"').strip("'")
    return meta, body.strip()


def chunk_body(body: str, max_chars: int = 900) -> list[str]:
    """Split markdown into paragraph-ish chunks for FTS + extractive answers."""
    parts = re.split(r"\n\s*\n", body)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        candidate = (buf + "\n\n" + part).strip() if buf else part
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            if len(part) <= max_chars:
                buf = part
            else:
                words = part.split()
                buf = ""
                for w in words:
                    trial = (buf + " " + w).strip()
                    if len(trial) > max_chars and buf:
                        chunks.append(buf)
                        buf = w
                    else:
                        buf = trial
        if buf and len(buf) >= max_chars * 0.7:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks or [body[:max_chars]]


def build() -> int:
    if not CORPUS.is_dir():
        print(f"Corpus missing: {CORPUS}", file=sys.stderr)
        return 1
    files = sorted(CORPUS.glob("*.md"))
    if not files:
        print("No markdown files in corpus", file=sys.stderr)
        return 1

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE docs (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            category TEXT,
            tags TEXT,
            path TEXT NOT NULL,
            body TEXT NOT NULL
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT,
            tags TEXT,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE docs_fts USING fts5(
            title, tags, category, body,
            content='docs', content_rowid='id',
            tokenize='porter unicode61'
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            title, tags, text,
            content='chunks', content_rowid='id',
            tokenize='porter unicode61'
        );
        """
    )

    doc_count = 0
    chunk_count = 0
    for path in files:
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)
        slug = meta.get("slug") or path.stem
        title = meta.get("title") or slug.replace("-", " ").title()
        category = meta.get("category") or "general"
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        tags_str = ", ".join(tags)
        rel = str(path.relative_to(ROOT)).replace("\\", "/")

        cur = conn.execute(
            "INSERT INTO docs (slug, title, category, tags, path, body) VALUES (?,?,?,?,?,?)",
            (slug, title, category, tags_str, rel, body),
        )
        doc_id = cur.lastrowid
        conn.execute(
            "INSERT INTO docs_fts(rowid, title, tags, category, body) VALUES (?,?,?,?,?)",
            (doc_id, title, tags_str, category, body),
        )
        doc_count += 1

        for i, chunk in enumerate(chunk_body(body)):
            cur = conn.execute(
                "INSERT INTO chunks (doc_id, slug, title, category, tags, chunk_index, text) "
                "VALUES (?,?,?,?,?,?,?)",
                (doc_id, slug, title, category, tags_str, i, chunk),
            )
            cid = cur.lastrowid
            conn.execute(
                "INSERT INTO chunks_fts(rowid, title, tags, text) VALUES (?,?,?,?)",
                (cid, title, tags_str, chunk),
            )
            chunk_count += 1

    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    conn.close()
    size = DB_PATH.stat().st_size
    print(f"Indexed {doc_count} docs / {chunk_count} chunks → {DB_PATH} ({size} bytes)")
    assert n == doc_count
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
