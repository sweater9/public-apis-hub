"""Offline crypto/blockchain knowledge base (FTS5 + extractive ask)."""
from kb.engine import (  # noqa: F401
    ask,
    ensure_index,
    get_doc,
    md_to_html,
    search,
    status,
)

__all__ = [
    "ask",
    "ensure_index",
    "get_doc",
    "md_to_html",
    "search",
    "status",
]
