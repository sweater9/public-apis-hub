"""Extractive ask + markdown HTML helpers for offline KB."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from kb.engine_core import (
    _clean_chunk,
    _connect,
    _fts_query,
    _query_terms,
    _score_chunk,
    search,
)

def ask(q: str, limit_sources: int = 5) -> dict:
    q = (q or "").strip()
    if not q:
        return {
            "answer": "Ask a crypto or blockchain question — for example: What is Ethereum staking?",
            "sources": [],
            "related": [],
            "query": q,
        }

    terms = _query_terms(q)
    fts = _fts_query(q)
    conn = _connect()
    chunks = []
    try:
        rows = conn.execute(
            """
            SELECT c.slug, c.title, c.category, c.tags, c.text, c.chunk_index,
                   bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY bm25(chunks_fts)
            LIMIT 24
            """,
            (fts,),
        ).fetchall()
        chunks = list(rows)
    except sqlite3.OperationalError:
        tokens = re.findall(r"[A-Za-z0-9_+\-]+", q.lower())
        fts2 = " OR ".join(f'"{t}"' for t in tokens[:8]) or '"crypto"'
        rows = conn.execute(
            """
            SELECT c.slug, c.title, c.category, c.tags, c.text, c.chunk_index,
                   bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY bm25(chunks_fts)
            LIMIT 24
            """,
            (fts2,),
        ).fetchall()
        chunks = list(rows)

    related = search(q, limit=6)
    conn.close()

    if not chunks and not related:
        return {
            "answer": (
                "I could not find that in the offline crypto knowledge base. "
                "Try different keywords (e.g. staking, wallets, DeFi, Bitcoin, rollups)."
            ),
            "sources": [],
            "related": [],
            "query": q,
        }

    ranked = []
    for r in chunks:
        text = r["text"]
        s = _score_chunk(text, terms) - float(r["score"]) * 0.15
        ranked.append((s, r))
    ranked.sort(key=lambda x: x[0], reverse=True)

    used_slugs: list[str] = []
    selected: list[Any] = []
    for _, r in ranked:
        if r["slug"] in used_slugs and sum(1 for s in selected if s["slug"] == r["slug"]) >= 2:
            continue
        selected.append(r)
        if r["slug"] not in used_slugs:
            used_slugs.append(r["slug"])
        if len(selected) >= 6:
            break

    if not selected and related:
        conn = _connect()
        for item in related[:3]:
            row = conn.execute(
                "SELECT slug, title, category, tags, body AS text, 0 AS chunk_index FROM docs WHERE slug=?",
                (item["slug"],),
            ).fetchone()
            if row:
                selected.append(row)
        conn.close()

    sources = []
    seen_source = set()
    for r in selected:
        if r["slug"] in seen_source:
            continue
        seen_source.add(r["slug"])
        cleaned = _clean_chunk(r["text"])
        snip = cleaned[:180] + ("…" if len(cleaned) > 180 else "")
        sources.append(
            {
                "title": r["title"],
                "slug": r["slug"],
                "snippet": snip,
                "category": r["category"] if "category" in r.keys() else None,
            }
        )
        if len(sources) >= max(1, min(limit_sources, 8)):
            break

    primary_slug = sources[0]["slug"] if sources else None
    primary_chunks = [r for r in selected if r["slug"] == primary_slug]
    other_chunks = [r for r in selected if r["slug"] != primary_slug]

    if primary_slug:
        conn2 = _connect()
        prow = conn2.execute("SELECT body FROM docs WHERE slug = ?", (primary_slug,)).fetchone()
        conn2.close()
        if prow and prow["body"]:
            primary_chunks = [
                {
                    "slug": primary_slug,
                    "title": sources[0]["title"],
                    "category": sources[0].get("category"),
                    "tags": "",
                    "text": prow["body"],
                    "chunk_index": 0,
                }
            ]

    def pieces_from(rows, max_sentences: int) -> list[str]:
        out = []
        budget = max_sentences
        for r in rows:
            text_val = r["text"] if not isinstance(r, dict) else r["text"]
            cleaned = _clean_chunk(text_val)
            if len(cleaned) < 40:
                continue
            cleaned = cleaned.replace(" - ", ". ")
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
            take = sentences[: min(budget, 6)]
            if not take:
                continue
            piece = " ".join(take)
            if len(piece) > 700:
                piece = piece[:697].rsplit(" ", 1)[0] + "…"
            out.append(piece)
            budget -= len(take)
            if budget <= 0:
                break
        return out

    lead = pieces_from(primary_chunks, max_sentences=7)
    support = pieces_from(other_chunks, max_sentences=2)

    paragraphs = []
    for p in lead + support:
        if any(p[:50].lower() in existing.lower() for existing in paragraphs):
            continue
        paragraphs.append(p)

    related_out = [
        {"title": r["title"], "slug": r["slug"], "snippet": r["snippet"]}
        for r in related
        if r["slug"] not in seen_source
    ][:5]

    if not paragraphs:
        answer = (
            "I found related articles but could not assemble a clear answer. "
            "Open a source below for the full article."
        )
    else:
        answer = paragraphs[0]
        for p in paragraphs[1:]:
            answer = answer.rstrip() + " " + p
        if len(answer) > 1100:
            answer = answer[:1097].rsplit(" ", 1)[0] + "…"

    return {
        "answer": answer,
        "sources": sources,
        "related": related_out,
        "query": q,
    }


_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def md_to_html(md: str) -> str:
    """Minimal markdown → HTML (no external deps)."""
    lines = md.splitlines()
    out: list[str] = []
    in_ul = False
    in_p = False

    def close_p():
        nonlocal in_p
        if in_p:
            out.append("</p>")
            in_p = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def inline(s: str) -> str:
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = _MD_BOLD.sub(r"<strong>\1</strong>", s)
        s = _MD_CODE.sub(r"<code>\1</code>", s)
        s = _MD_LINK.sub(r'<a href="\2" rel="noopener">\1</a>', s)
        return s

    for line in lines:
        if not line.strip():
            close_p()
            close_ul()
            continue
        if line.startswith("### "):
            close_p(); close_ul(); out.append(f"<h3>{inline(line[4:].strip())}</h3>")
        elif line.startswith("## "):
            close_p(); close_ul(); out.append(f"<h2>{inline(line[3:].strip())}</h2>")
        elif line.startswith("# "):
            close_p(); close_ul(); out.append(f"<h1>{inline(line[2:].strip())}</h1>")
        elif line.lstrip().startswith("- "):
            close_p()
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{inline(line.lstrip()[2:].strip())}</li>")
        else:
            close_ul()
            if not in_p:
                out.append("<p>"); in_p = True
            else:
                out.append(" ")
            out.append(inline(line.strip()))
    close_p(); close_ul()
    return "\n".join(out)
