#!/usr/bin/env python3
"""Public APIs Hub — catalog + CORS proxy + banking KB page."""
from __future__ import annotations
import ipaddress, json, os, socket, time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from kb import ask as kb_ask, ensure_index as kb_ensure_index, search as kb_search, status as kb_status
from kb.banking_hooks import register_banking

APP_DIR = Path(__file__).resolve().parent
CATALOG_PATH = APP_DIR / "catalog.json"
PROXY_TIMEOUT = 15
PROXY_MAX_BYTES = 2_000_000
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 60
app = Flask(__name__, static_folder="static", static_url_path="/static")
try:
    kb_ensure_index()
except Exception as _kb_exc:
    app.logger.warning("KB index build failed: %s", _kb_exc)

def load_catalog():
    data_dir = APP_DIR / "data"
    if data_dir.is_dir():
        items = []
        for path in sorted(data_dir.glob("*.json")):
            with path.open(encoding="utf-8") as f:
                chunk = json.load(f)
            if isinstance(chunk, list):
                items.extend(chunk)
        if items:
            return items
    with CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)

CATALOG = load_catalog()

def catalog_hosts():
    hosts = set()
    for item in CATALOG:
        try:
            host = urlparse(item.get("link") or "").hostname
        except Exception:
            host = None
        if host:
            hosts.add(host.lower().rstrip("."))
    return hosts

EXTRA_ALLOWED_HOSTS = {"api.coingecko.com","api.llama.fi","api.gemini.com","api.coinlore.net","api.coinpaprika.com","mempool.space","www.corpstacking.com","intel.twzrd.xyz"}
ALLOWED_HOSTS = catalog_hosts() | {h.lower().rstrip(".") for h in EXTRA_ALLOWED_HOSTS}
_rate_buckets = defaultdict(deque)

def rate_limited(ip):
    now = time.time()
    q = _rate_buckets[ip]
    while q and now - q[0] > RATE_LIMIT_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT_MAX:
        return True
    q.append(now)
    return False

def is_private_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified or addr in (ipaddress.ip_address("169.254.169.254"),)

def host_allowed(hostname):
    if not hostname:
        return False
    h = hostname.lower().rstrip(".")
    if h in ALLOWED_HOSTS:
        return True
    return any(h == a or h.endswith("." + a) for a in ALLOWED_HOSTS)

def resolve_and_check(hostname):
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return False, f"DNS resolution failed: {exc}"
    for info in infos:
        ip = info[4][0]
        if is_private_ip(ip):
            return False, f"blocked private/reserved IP: {ip}"
    return True, "ok"

def validate_proxy_url(raw):
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
    netloc = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
    clean = f"{parsed.scheme}://{netloc}{parsed.path or ''}"
    if parsed.query:
        clean += f"?{parsed.query}"
    return clean, None

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "public-apis-hub", "catalog_count": len(CATALOG), "categories": sorted({c["category"] for c in CATALOG}), "allowed_hosts": len(ALLOWED_HOSTS)})

@app.get("/api/catalog")
def catalog():
    category = (request.args.get("category") or "").strip()
    q = (request.args.get("q") or "").strip().lower()
    items = CATALOG
    if category:
        items = [i for i in items if i["category"].lower() == category.lower()]
    if q:
        items = [i for i in items if q in i["api"].lower() or q in i["description"].lower() or q in i["link"].lower() or q in i["category"].lower()]
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
    headers = {"User-Agent": "public-apis-hub-proxy/1.0", "Accept": request.headers.get("Accept", "application/json, text/plain, */*")}
    try:
        upstream = requests.get(clean, headers=headers, timeout=PROXY_TIMEOUT, stream=True, allow_redirects=False) if request.method != "POST" else requests.post(clean, data=request.get_data(), headers={**headers, "Content-Type": request.headers.get("Content-Type", "application/json")}, timeout=PROXY_TIMEOUT, stream=True, allow_redirects=False)
    except requests.Timeout:
        return jsonify({"error": "upstream timeout"}), 504
    except requests.RequestException as exc:
        return jsonify({"error": f"upstream error: {exc}"}), 502
    if upstream.is_redirect or upstream.status_code in (301, 302, 303, 307, 308):
        upstream.close()
        return jsonify({"error": "redirects not followed for SSRF safety"}), 502
    chunks, total = [], 0
    for chunk in upstream.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > PROXY_MAX_BYTES:
            upstream.close()
            return jsonify({"error": "response too large"}), 502
        chunks.append(chunk)
    resp = Response(b"".join(chunks), status=upstream.status_code, content_type=upstream.headers.get("Content-Type", "application/octet-stream"))
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["X-Proxy-Upstream"] = urlparse(clean).hostname or ""
    return resp

@app.get("/api/kb/status")
def kb_status_route():
    try:
        kb_ensure_index()
        return jsonify(kb_status())
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.get("/api/kb/search")
def kb_search_route():
    q = (request.args.get("q") or "").strip()
    try:
        limit = min(int(request.args.get("limit") or 8), 20)
    except ValueError:
        limit = 8
    kb_ensure_index()
    scope = (request.args.get("scope") or "").strip() or None
    results = kb_search(q, limit=limit, scope=scope)
    payload = {"query": q, "results": results, "hits": results, "count": len(results)}
    if scope:
        payload["scope"] = scope
    return jsonify(payload)

@app.route("/api/kb/ask", methods=["GET", "POST"])
def kb_ask_route():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        q = (body.get("q") or body.get("query") or request.args.get("q") or "").strip()
        scope = (body.get("scope") or request.args.get("scope") or "").strip() or None
        try:
            limit_sources = min(int(body.get("limit_sources") or request.args.get("limit_sources") or 5), 10)
        except ValueError:
            limit_sources = 5
    else:
        q = (request.args.get("q") or request.args.get("query") or "").strip()
        scope = (request.args.get("scope") or "").strip() or None
        try:
            limit_sources = min(int(request.args.get("limit_sources") or 5), 10)
        except ValueError:
            limit_sources = 5
    kb_ensure_index()
    return jsonify(kb_ask(q, limit_sources=limit_sources, scope=scope))

@app.get("/api/kb/doc/<slug>")
def kb_doc_route(slug: str):
    from kb import get_doc
    fmt = (request.args.get("format") or "json").strip().lower()
    doc = get_doc(slug)
    if not doc:
        return jsonify({"error": "not found"}), 404
    if fmt in ("markdown", "md"):
        return Response(doc["markdown"], mimetype="text/markdown; charset=utf-8")
    if fmt == "html":
        return Response(doc["html"], mimetype="text/html; charset=utf-8")
    return jsonify(doc)

@app.get("/kb")
def kb_page():
    return send_from_directory(APP_DIR / "static", "kb.html")

@app.get("/kb/<slug>")
def kb_article_page(slug: str):
    return send_from_directory(APP_DIR / "static", "kb.html")

@app.get("/")
def index():
    return send_from_directory(APP_DIR / "static", "landing.html")


@app.get("/catalog")
def catalog_page():
    return send_from_directory(APP_DIR / "static", "index.html")

@app.get("/tools")
def tools():
    return send_from_directory(APP_DIR / "static", "tools.html")

register_banking(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
