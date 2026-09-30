"""Offline crypto/blockchain knowledge base engine (FTS5 + extractive ask)."""
from kb.ask_engine import ask, md_to_html  # noqa: F401
from kb.engine_core import (  # noqa: F401
    ensure_index,
    get_doc,
    search,
    status,
)

__all__ = ["ask", "ensure_index", "get_doc", "md_to_html", "search", "status"]
