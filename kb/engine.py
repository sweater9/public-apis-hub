"""Offline crypto/blockchain knowledge base engine (FTS5 + extractive ask)."""
from __future__ import annotations

from kb.ask_engine import ask as _ask_raw, md_to_html  # noqa: F401
from kb.engine_core import (  # noqa: F401
    ensure_index,
    get_doc,
    resolve_scope_categories,
    search,
    status,
)

__all__ = ["ask", "ensure_index", "get_doc", "md_to_html", "search", "status"]


def ask(q: str, limit_sources: int = 5, scope: str | None = None) -> dict:
    """Ask with optional scope=banking filter.

    Prefer native ask_engine scope when available; otherwise filter sources after
    retrieval and fall back to scoped search for related docs.
    """
    try:
        return _ask_raw(q, limit_sources=limit_sources, scope=scope)
    except TypeError:
        # Older ask_engine without scope kwarg
        pass

    result = _ask_raw(q, limit_sources=limit_sources)
    cats = resolve_scope_categories(scope)
    if not cats:
        return result

    sources = [s for s in (result.get("sources") or []) if (s.get("category") or "") in cats]
    if not sources:
        # Re-drive via scoped search hits as weak fallback
        hits = search(q, limit=max(3, limit_sources), scope=scope)
        sources = [
            {
                "title": h.get("title"),
                "slug": h.get("slug"),
                "snippet": h.get("snippet"),
                "category": h.get("category"),
            }
            for h in hits[:limit_sources]
        ]
        if not sources:
            result["answer"] = (
                "I could not find that in the offline knowledge base. "
                "Try banking/KYC keywords (e.g. KYC, corporate banking, FI vs NBFI, OFAC)."
            )
            result["sources"] = []
            result["related"] = []
            if scope:
                result["scope"] = str(scope).strip().lower()
            return result
        # Load primary doc lead as answer when we only have search hits
        primary = sources[0]
        doc = get_doc(primary["slug"])
        if doc and doc.get("markdown"):
            # First non-empty paragraph after title
            paras = [p.strip() for p in doc["markdown"].split("\n\n") if p.strip() and not p.strip().startswith("#") and not p.strip().startswith("---")]
            if paras:
                result["answer"] = paras[0][:1100]

    related = search(q, limit=6, scope=scope)
    seen = {s.get("slug") for s in sources}
    result["sources"] = sources
    result["related"] = [
        {"title": h["title"], "slug": h["slug"], "snippet": h.get("snippet")}
        for h in related
        if h.get("slug") not in seen
    ][:5]
    if scope:
        result["scope"] = str(scope).strip().lower()
    return result
