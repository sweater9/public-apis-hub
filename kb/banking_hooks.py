"""Banking page routes for /banking and /banking/<slug>."""
from __future__ import annotations

from pathlib import Path

from flask import Flask, send_from_directory

APP_DIR = Path(__file__).resolve().parents[1]


def register_banking(app: Flask) -> None:
    @app.get("/banking")
    def banking_page():
        return send_from_directory(APP_DIR / "static", "banking.html")

    @app.get("/banking/<slug>")
    def banking_article_page(slug: str):
        return send_from_directory(APP_DIR / "static", "banking.html")
