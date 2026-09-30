#!/usr/bin/env python3
"""Public APIs Hub — Cryptocurrency & Blockchain catalog + CORS proxy."""
from __future__ import annotations

import ipaddress
import json
import socket
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

APP_DIR = Path(__file__).resolve().parent
CATALOG_PATH = APP_DIR / "catalog.json"
PROXY_TIMEOUT = 15
PROXY_MAX_BYTES = 2_000_000  # 2 MB
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 60

app = Flask(__name__, static_folder="static", static_url_path="/static")

# --- catalog ---
def load_catalog() -> list[dict]:
    with CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


CATALOG = load_catalog()


def catalog_hosts() -> set[str]:
    hosts: set[str] = set()
    for item in CATALOG:
        link = item.get("link") or ""
        try:
            host = urlparse(link).hostname
        except Exception:
            host = None
        if host:
            hosts.add(host.lower().rstrip("."))
    return hosts


ALLOWED_HOSTS = catalog_hosts()

# --- rate limit (in-memory, per IP) ---
_rate_buckets: dict[str, deque] = defaultdict(deque)


def rate_limited(ip: str) -> bool:
    now = time.time()
    q = _rate_buckets[ip]
    while q and now - q[0] > RATE_LIMIT_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT_MAX:
        return True
    q.append(now)
    return False


# --- SSRF helpers ---
def is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or addr in (ipaddress.ip_address("169.254.169.254"),)
    )


def host_allowed(hostname: str) -> bool:
    if not hostname:
        return False
    h = hostname.lower().rstrip(".")
    if h in ALLOWED_HOSTS:
        return True
    for allowed in ALLOWED_HOSTS:
        if h == allowed or h.endswith("." + allowed):
            return True
    return False


def resolve_and_check(hostname: str) -> tuple[bool, str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return False, f"DNS resolution failed: {exc}"
    for info in infos:
        ip = info[4][0]
        if is_private_ip(ip):
            return False, f"blocked private/reserved IP: {ip}"
    return True, "ok"


def validate_proxy_url(raw: str) -> tuple[str | None, str | None]:
    if not raw:
        return None, "missing url"
    try:
        parsed = urlparse(raw)
    except Exception:
        return None, "invalid url"
    if parsed.scheme not in ("http", "https"):
        return None, "only http/https allowed"
    if not parsed.hostname:
        return None, "missing hostname"
    host = parsed.hostname.lower()
    if host in ("localhost", "metadata.google.internal") or host.endswith(".local"):
        return None, "blocked hostname"
    if not host_allowed(host):
        return None, "hostname not in catalog allowlist"
    ok, reason = resolve_and_check(host)
    if not ok:
        return None, reason
    netloc = parsed.hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    clean = f"{parsed.scheme}://{netloc}{parsed.path or ''}"
    if parsed.query:
        clean += f"?{parsed.query}"
    return clean, None


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "service": "public-apis-hub",
            "catalog_count": len(CATALOG),
            "categories": sorted({c["category"] for c in CATALOG}),
            "allowed_hosts": len(ALLOWED_HOSTS),
        }
    )


@app.get("/api/catalog")
def catalog():
    category = (request.args.get("category") or "").strip()
    q = (request.args.get("q") or "").strip().lower()
    auth = (request.args.get("auth") or "").strip()
    https = (request.args.get("https") or "").strip()
    cors = (request.args.get("cors") or "").strip()

    items = CATALOG
    if category:
        items = [i for i in items if i["category"].lower() == category.lower()]
    if auth:
        items = [i for i in items if i["auth"].lower() == auth.lower()]
    if https:
        items = [i for i in items if i["https"].lower() == https.lower()]
    if cors:
        items = [i for i in items if i["cors"].lower() == cors.lower()]
    if q:
        items = [
            i
            for i in items
            if q in i["api"].lower()
            or q in i["description"].lower()
            or q in i["link"].lower()
            or q in i["category"].lower()
        ]
    return jsonify({"count": len(items), "items": items})


@app.route("/api/proxy", methods=["GET", "POST", "OPTIONS"])
def proxy():
    if request.method == "OPTIONS":
        resp = Response(status=204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        return resp

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if rate_limited(client_ip):
        return jsonify({"error": "rate limit exceeded"}), 429

    raw_url = request.args.get("url") or (request.get_json(silent=True) or {}).get("url")
    clean, err = validate_proxy_url(raw_url)
    if err:
        return jsonify({"error": err}), 400

    headers = {
        "User-Agent": "public-apis-hub-proxy/1.0",
        "Accept": request.headers.get("Accept", "application/json, text/plain, */*"),
    }
    for h in ("Authorization", "X-Api-Key", "X-API-KEY"):
        if h in request.headers:
            headers[h] = request.headers[h]

    try:
        if request.method == "POST":
            body = request.get_data()
            ctype = request.headers.get("Content-Type", "")
            if "application/json" in ctype:
                payload = request.get_json(silent=True) or {}
                if "url" in payload and set(payload.keys()) <= {"url", "body", "headers"}:
                    body = json.dumps(payload.get("body") or {}).encode("utf-8")
                    ctype = "application/json"
            upstream = requests.post(
                clean,
                data=body,
                headers={**headers, "Content-Type": ctype or "application/json"},
                timeout=PROXY_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
        else:
            upstream = requests.get(
                clean,
                headers=headers,
                timeout=PROXY_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
    except requests.Timeout:
        return jsonify({"error": "upstream timeout"}), 504
    except requests.RequestException as exc:
        return jsonify({"error": f"upstream error: {exc}"}), 502

    if upstream.is_redirect or upstream.status_code in (301, 302, 303, 307, 308):
        upstream.close()
        return jsonify({"error": "redirects not followed for SSRF safety"}), 502

    chunks = []
    total = 0
    for chunk in upstream.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > PROXY_MAX_BYTES:
            upstream.close()
            return jsonify({"error": "response too large"}), 502
        chunks.append(chunk)
    content = b"".join(chunks)
    content_type = upstream.headers.get("Content-Type", "application/octet-stream")
    resp = Response(content, status=upstream.status_code, content_type=content_type)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["X-Proxy-Upstream"] = urlparse(clean).hostname or ""
    return resp


@app.get("/")
def index():
    return send_from_directory(APP_DIR / "static", "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
