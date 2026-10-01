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

_DEF_RE = re.compile(
    r"\b(what\s+is|what\s+are|what'?s|define|definition\s+of|meaning\s+of)\b",
    re.I,
)
_HOW_RE = re.compile(
    r"\b(how\s+does|how\s+do|how\s+to|how\s+can|how\s+is|explain\s+how|walk\s+me\s+through)\b",
    re.I,
)
_COMPARE_RE = re.compile(
    r"\b(vs\.?|versus|compared?\s+(to|with)|difference\s+between|differences?\s+between|compare)\b",
    re.I,
)
_OVERVIEW_SLUG = re.compile(
    r"(^what-is-|-basics$|-overview$|^glossary-)",
    re.I,
)
_PROCESS_SLUG = re.compile(
    r"(^how-|-explained$|-lifecycle|-works)",
    re.I,
)


def _question_type(q: str) -> str:
    if _COMPARE_RE.search(q):
        return "compare"
    if _DEF_RE.search(q):
        return "definition"
    if _HOW_RE.search(q):
        return "how"
    return "general"


def _topic_terms(q: str, terms: list[str]) -> list[str]:
    """Content terms after stripping question-framing words."""
    drop = {
        "what",
        "whats",
        "define",
        "definition",
        "meaning",
        "explain",
        "how",
        "does",
        "do",
        "did",
        "can",
        "could",
        "should",
        "would",
        "vs",
        "versus",
        "compare",
        "compared",
        "difference",
        "differences",
        "between",
        "about",
        "tell",
        "me",
        "please",
    }
    out = [t for t in terms if t not in drop]
    # Trailing "work(s)" in how-questions is usually a verb ("how does X work"),
    # not part of the topic — but keep it for phrases like "proof of work".
    ql = q.lower()
    if out and out[-1] in {"work", "works", "working"} and _HOW_RE.search(ql):
        if not re.search(r"\bproof\s+of\s+work\b", ql):
            out = out[:-1]
    return out or terms


def _slug_tokens(slug: str) -> set[str]:
    return {p for p in re.split(r"[-_]+", (slug or "").lower()) if p and len(p) > 1}


def _title_blob(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _doc_relevance(slug: str, title: str, topic: list[str], qtype: str) -> float:
    """Boost/penalize whole documents by question type and topic fit."""
    if not topic:
        return 0.0
    slug_l = (slug or "").lower()
    title_l = _title_blob(title)
    stoks = _slug_tokens(slug_l)
    topic_set = set(topic)
    hit = topic_set & stoks
    score = 0.0

    # Title/slug coverage of topic terms
    score += 2.5 * len(hit)
    for t in topic:
        if title_l.startswith(t + " ") or title_l == t:
            score += 2.0
        elif f" {t} " in f" {title_l} ":
            score += 1.0
        if slug_l == t or slug_l.startswith(t + "-") or slug_l.endswith("-" + t):
            score += 1.2

    # Exact-ish overview match: bitcoin-basics for topic {bitcoin}
    if topic_set <= stoks and _OVERVIEW_SLUG.search(slug_l):
        score += 4.0
    if slug_l in {f"what-is-{t}" for t in topic} or slug_l in {f"{t}-basics" for t in topic}:
        score += 5.0
    if slug_l in {"-".join(topic), "-".join(reversed(topic))}:
        score += 4.5
    # proof-of-work for topic proof, work
    if topic and all(t in stoks for t in topic):
        score += 3.0

    if qtype == "definition":
        if _OVERVIEW_SLUG.search(slug_l):
            score += 3.5
        if _PROCESS_SLUG.search(slug_l) and not (topic_set <= stoks and len(topic) >= 2):
            # Narrow how-/process pages lose to basics for plain "what is X"
            score -= 2.0
        # Single-topic definition: penalize subtopic pages that add extra tokens
        if len(topic) == 1:
            extra = stoks - topic_set - {"basics", "overview", "what", "is", "glossary", "a", "an"}
            if extra and topic[0] in stoks and not _OVERVIEW_SLUG.search(slug_l):
                score -= 2.5 * min(3, len(extra))
    elif qtype == "how":
        if _PROCESS_SLUG.search(slug_l):
            score += 3.0
        if topic_set and topic_set <= stoks:
            score += 3.5
            # Exact multi-term slug (bitcoin-halving) beats overview pages
            if stoks - topic_set <= {"how", "explained", "works", "overview"}:
                score += 4.0
        if _OVERVIEW_SLUG.search(slug_l):
            # Overview/basics only win when topic is a single entity with no process page
            if topic_set <= stoks and len(topic) == 1:
                score += 0.5
            else:
                score -= 2.5
    elif qtype == "compare":
        # Prefer pages that mention multiple topic terms in title/slug
        if len(hit) >= 2:
            score += 4.0
        if "vs" in stoks or "versus" in stoks or "compared" in title_l:
            score += 2.0

    return score


def _definitional_boost(text: str, topic: list[str]) -> float:
    """Prefer chunks that actually define the topic entity."""
    if not topic:
        return 0.0
    cleaned = _clean_chunk(text)
    low = cleaned.lower()
    head = low[:220]
    boost = 0.0
    for t in topic:
        # "Bitcoin (BTC) is ..." / "Bitcoin is ..."
        if re.search(rf"\b{re.escape(t)}\b(?:\s*\([^)]+\))?\s+(is|are|refers\s+to|means)\b", head):
            boost += 6.0
        elif re.search(rf"\b{re.escape(t)}\b(?:\s*\([^)]+\))?\s+(is|are)\b", low):
            boost += 3.0
        # Glossary style: "An address is ..." when topic is address
        if re.search(rf"\b(a|an|the)\s+{re.escape(t)}\b\s+(is|are)\b", head):
            boost += 5.0
    # Early position of topic term
    for t in topic:
        pos = head.find(t)
        if pos == 0:
            boost += 1.5
        elif 0 < pos < 40:
            boost += 0.8
    return boost


def _rank_chunk(row: Any, terms: list[str], topic: list[str], qtype: str) -> float:
    text = row["text"]
    base = _score_chunk(text, terms) - float(row["score"]) * 0.15
    base += _doc_relevance(row["slug"], row["title"], topic, qtype)
    if qtype == "definition":
        base += _definitional_boost(text, topic)
        # Prefer earlier chunks of an article (leads usually define)
        try:
            idx = int(row["chunk_index"])
        except Exception:
            idx = 0
        if idx == 0:
            base += 1.25
        elif idx == 1:
            base += 0.25
    elif qtype == "how":
        low = text.lower()
        if any(x in low for x in ("step", "process", "first", "then", "mechanism")):
            base += 1.0
        base += _definitional_boost(text, topic) * 0.25
    return base


def _fetch_chunks(conn: sqlite3.Connection, fts: str, q: str) -> list[sqlite3.Row]:
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
        return list(rows)
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
        return list(rows)


def _row_field(r: Any, key: str, default=None):
    if isinstance(r, dict):
        return r.get(key, default)
    try:
        return r[key]
    except Exception:
        return default


def _sentences(cleaned: str) -> list[str]:
    cleaned = cleaned.replace(" - ", ". ")
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]


def _is_definition_sentence(sent: str, topic: list[str]) -> bool:
    low = sent.lower()
    if not topic:
        return bool(re.search(r"\b(is|are|refers to|means)\b", low[:80]))
    for t in topic:
        if re.search(
            rf"\b((a|an|the)\s+)?{re.escape(t)}\b(?:\s*\([^)]+\))?\s+(is|are|refers\s+to|means)\b",
            low,
        ):
            return True
    return False


def _load_doc_body(slug: str) -> str | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT body FROM docs WHERE slug = ?", (slug,)).fetchone()
        return row["body"] if row else None
    finally:
        conn.close()


def _pick_definition_lead(primary_body: str, topic: list[str], max_sentences: int = 3) -> str:
    cleaned = _clean_chunk(primary_body)
    sents = _sentences(cleaned)
    if not sents:
        return ""
    # Prefer starting at the first definitional sentence about the topic
    start = 0
    for i, s in enumerate(sents):
        if _is_definition_sentence(s, topic):
            start = i
            break
    take: list[str] = []
    for s in sents[start:]:
        # Stop before list-y "Important ideas:" / "Key properties:" dumps
        if re.match(r"^(important ideas|key (ideas|properties|points)|notes)\b", s, re.I):
            break
        take.append(s)
        if len(take) >= max_sentences:
            break
    piece = " ".join(take)
    if len(piece) > 700:
        piece = piece[:697].rsplit(" ", 1)[0] + "…"
    return piece


def _support_sentences(
    rows: list[Any],
    topic: list[str],
    qtype: str,
    exclude_prefix: str,
    max_sentences: int = 2,
) -> list[str]:
    out: list[str] = []
    budget = max_sentences
    for r in rows:
        text_val = _row_field(r, "text", "")
        cleaned = _clean_chunk(text_val)
        if len(cleaned) < 40:
            continue
        sents = _sentences(cleaned)
        chosen: list[str] = []
        for s in sents:
            low = s.lower()
            # Must mention at least one topic term to stay on-subject
            if topic and not any(t in low for t in topic):
                continue
            if qtype == "definition":
                # Skip repeating a full definition of the asked topic
                if _is_definition_sentence(s, topic):
                    continue
                # For multi-term topics (bitcoin + halving), prefer sentences that
                # touch the more specific terms, not only the parent entity.
                if len(topic) >= 2 and not any(t in low for t in topic[1:]):
                    continue
            chosen.append(s)
            if len(chosen) >= min(budget, 2 if qtype == "definition" else 3):
                break
        if not chosen:
            continue
        piece = " ".join(chosen)
        if exclude_prefix and piece[:50].lower() in exclude_prefix.lower():
            continue
        if len(piece) > 500:
            piece = piece[:497].rsplit(" ", 1)[0] + "…"
        out.append(piece)
        budget -= len(chosen)
        if budget <= 0:
            break
    return out


def _formulate_answer(
    qtype: str,
    topic: list[str],
    primary_slug: str | None,
    primary_title: str | None,
    selected: list[Any],
    sources: list[dict],
) -> str:
    if not primary_slug and not selected:
        return (
            "I found related articles but could not assemble a clear answer. "
            "Open a source below for the full article."
        )

    primary_chunks = [r for r in selected if _row_field(r, "slug") == primary_slug]
    other_chunks = [r for r in selected if _row_field(r, "slug") != primary_slug]

    body = _load_doc_body(primary_slug) if primary_slug else None
    if body:
        primary_chunks = [
            {
                "slug": primary_slug,
                "title": primary_title or (sources[0]["title"] if sources else primary_slug),
                "text": body,
                "chunk_index": 0,
            }
        ]

    paragraphs: list[str] = []

    if qtype == "definition":
        primary_fits_topic = False
        if primary_slug and topic:
            stoks = _slug_tokens(primary_slug)
            primary_fits_topic = set(topic) <= stoks or any(
                primary_slug == f"{t}-basics" or primary_slug == f"what-is-{t}" for t in topic
            )

        lead = ""
        if body:
            lead = _pick_definition_lead(body, topic, max_sentences=4)
        if not lead and primary_chunks:
            lead = _pick_definition_lead(
                _row_field(primary_chunks[0], "text", ""), topic, max_sentences=4
            )
        # Only steal a definition from another doc when primary is not the topic page
        if (
            lead
            and not primary_fits_topic
            and not _is_definition_sentence((lead.split(". ")[0] + "."), topic)
        ):
            for r in other_chunks:
                alt_body = _load_doc_body(_row_field(r, "slug")) or _row_field(r, "text", "")
                alt = _pick_definition_lead(alt_body, topic, max_sentences=3)
                if alt and _is_definition_sentence((alt.split(". ")[0] + "."), topic):
                    lead = alt
                    break
        if lead:
            paragraphs.append(lead)
        support = _support_sentences(
            other_chunks, topic, qtype, lead[:60] if lead else "", max_sentences=2
        )
        paragraphs.extend(support)
    elif qtype == "how":
        # Lead with process-oriented sentences from the best-matching doc
        cleaned = _clean_chunk(_row_field(primary_chunks[0], "text", "") if primary_chunks else "")
        sents = _sentences(cleaned)[:6]
        if sents:
            piece = " ".join(sents)
            if len(piece) > 800:
                piece = piece[:797].rsplit(" ", 1)[0] + "…"
            paragraphs.append(piece)
        paragraphs.extend(
            _support_sentences(other_chunks, topic, qtype, paragraphs[0][:60] if paragraphs else "", 2)
        )
    elif qtype == "compare":
        cleaned = _clean_chunk(_row_field(primary_chunks[0], "text", "") if primary_chunks else "")
        sents = _sentences(cleaned)[:5]
        if sents:
            paragraphs.append(" ".join(sents))
        paragraphs.extend(
            _support_sentences(other_chunks, topic, qtype, paragraphs[0][:60] if paragraphs else "", 2)
        )
    else:
        cleaned = _clean_chunk(_row_field(primary_chunks[0], "text", "") if primary_chunks else "")
        sents = _sentences(cleaned)[:5]
        if sents:
            paragraphs.append(" ".join(sents))
        paragraphs.extend(
            _support_sentences(other_chunks, topic, qtype, paragraphs[0][:60] if paragraphs else "", 2)
        )

    # Dedup near-identical paragraphs
    final: list[str] = []
    for p in paragraphs:
        if not p or len(p) < 40:
            continue
        if any(p[:50].lower() in existing.lower() for existing in final):
            continue
        final.append(p)

    if not final:
        return (
            "I found related articles but could not assemble a clear answer. "
            "Open a source below for the full article."
        )

    answer = final[0]
    for p in final[1:]:
        answer = answer.rstrip() + " " + p
    if len(answer) > 1100:
        answer = answer[:1097].rsplit(" ", 1)[0] + "…"
    return answer


def ask(q: str, limit_sources: int = 5) -> dict:
    q = (q or "").strip()
    if not q:
        return {
            "answer": "Ask a crypto or blockchain question — for example: What is Ethereum staking?",
            "sources": [],
            "related": [],
            "query": q,
        }

    qtype = _question_type(q)
    terms = _query_terms(q)
    topic = _topic_terms(q, terms)
    # Retrieve on topic terms so filler verbs (how/does/work) do not AND-out hits
    fts = _fts_query(q, topic or terms)
    conn = _connect()
    chunks = _fetch_chunks(conn, fts, q)
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

    ranked: list[tuple[float, Any]] = []
    for r in chunks:
        ranked.append((_rank_chunk(r, terms, topic, qtype), r))
    ranked.sort(key=lambda x: x[0], reverse=True)

    used_slugs: list[str] = []
    selected: list[Any] = []
    top_score = ranked[0][0] if ranked else 0.0
    for s, r in ranked:
        # Soft relevance floor: skip very weak leftovers when we already have strong hits
        if selected and top_score > 8 and s < top_score * 0.25:
            continue
        if r["slug"] in used_slugs and sum(1 for x in selected if x["slug"] == r["slug"]) >= 2:
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

    # Re-order selected docs by doc-level relevance for question type
    def doc_key(r: Any) -> float:
        # Best chunk score for this slug among ranked
        slug = r["slug"]
        chunk_best = max((sc for sc, row in ranked if row["slug"] == slug), default=0.0)
        return chunk_best + _doc_relevance(slug, r["title"], topic, qtype)

    # Stable unique slug order by doc_key
    slug_order: list[str] = []
    slug_best_row: dict[str, Any] = {}
    for r in sorted(selected, key=doc_key, reverse=True):
        slug = r["slug"]
        if slug not in slug_best_row:
            slug_best_row[slug] = r
            slug_order.append(slug)

    # Promote the most question-appropriate doc when an obvious slug exists
    preferred: list[str] = []
    if qtype == "definition" and len(topic) == 1:
        preferred = [
            f"{topic[0]}-basics",
            f"what-is-{topic[0]}",
            f"glossary-{topic[0]}",
            "-".join(topic),
        ]
    elif qtype == "definition" and len(topic) >= 2:
        preferred = ["-".join(topic), "-".join(reversed(topic)), f"what-is-{'-'.join(topic)}"]
    elif qtype == "how" and topic:
        preferred = ["-".join(topic), f"how-{'-'.join(topic)}", f"{'-'.join(topic)}-explained"]
        if len(topic) == 1:
            preferred += [f"how-{topic[0]}-works", f"{topic[0]}-basics"]

    if preferred:
        for pref in preferred:
            if pref in slug_best_row and slug_order and slug_order[0] != pref:
                slug_order = [pref] + [s for s in slug_order if s != pref]
                break
        if slug_order and slug_order[0] not in preferred:
            for sc, row in ranked:
                if row["slug"] in preferred:
                    if row["slug"] not in slug_best_row:
                        slug_best_row[row["slug"]] = row
                        selected.append(row)
                    slug_order = [row["slug"]] + [s for s in slug_order if s != row["slug"]]
                    break

    sources: list[dict] = []
    seen_source: set[str] = set()
    ordered_rows: list[Any] = []
    for slug in slug_order:
        # Prefer the highest-scoring chunk for snippet; keep all selected chunks for assembly
        rows_for = [r for r in selected if r["slug"] == slug]
        ordered_rows.extend(rows_for)
        r0 = slug_best_row[slug]
        if slug in seen_source:
            continue
        seen_source.add(slug)
        cleaned = _clean_chunk(r0["text"])
        # For definition primary, prefer definitional snippet from full body
        if qtype == "definition" and len(sources) == 0:
            body = _load_doc_body(slug)
            if body:
                lead = _pick_definition_lead(body, topic, max_sentences=2)
                if lead:
                    cleaned = lead
        snip = cleaned[:180] + ("…" if len(cleaned) > 180 else "")
        sources.append(
            {
                "title": r0["title"],
                "slug": slug,
                "snippet": snip,
                "category": _row_field(r0, "category"),
            }
        )
        if len(sources) >= max(1, min(limit_sources, 8)):
            break

    # Relevance gate: weak match for definitional questions
    best_doc_score = doc_key(slug_best_row[slug_order[0]]) if slug_order else 0.0
    if qtype == "definition" and topic and best_doc_score < 4.0 and ranked and ranked[0][0] < 6.0:
        return {
            "answer": (
                "I could not find a clear definition for that in the offline knowledge base. "
                "Try a more specific term, or browse related articles below."
            ),
            "sources": sources[:3],
            "related": [
                {"title": r["title"], "slug": r["slug"], "snippet": r["snippet"]}
                for r in related
                if r["slug"] not in seen_source
            ][:5],
            "query": q,
        }

    primary_slug = sources[0]["slug"] if sources else None
    primary_title = sources[0]["title"] if sources else None
    answer = _formulate_answer(
        qtype, topic, primary_slug, primary_title, ordered_rows or selected, sources
    )

    related_out = [
        {"title": r["title"], "slug": r["slug"], "snippet": r["snippet"]}
        for r in related
        if r["slug"] not in seen_source
    ][:5]

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
        s = (
            s.replace("&", "&")
            .replace("<", "<")
            .replace(">", ">")
        )
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
            close_p()
            close_ul()
            out.append(f"<h3>{inline(line[4:].strip())}</h3>")
        elif line.startswith("## "):
            close_p()
            close_ul()
            out.append(f"<h2>{inline(line[3:].strip())}</h2>")
        elif line.startswith("# "):
            close_p()
            close_ul()
            out.append(f"<h1>{inline(line[2:].strip())}</h1>")
        elif line.lstrip().startswith("- "):
            close_p()
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(line.lstrip()[2:].strip())}</li>")
        else:
            close_ul()
            if not in_p:
                out.append("<p>")
                in_p = True
            else:
                out.append(" ")
            out.append(inline(line.strip()))
    close_p()
    close_ul()
    return "\n".join(out)
