# public-apis-hub

Standalone Flask catalog + CORS proxy for **Cryptocurrency** and **Blockchain** APIs sourced from [public-apis/public-apis](https://github.com/public-apis/public-apis).

Built for the Projject Api room. Does **not** depend on multi-agent-ai-system or scout-hub.

## Features

- Dark Grok-like UI with search/filter by name, auth, HTTPS, CORS, category
- `GET /api/catalog` — JSON list (defaults to full crypto+blockchain dataset)
- `GET /api/proxy?url=<encoded>` — server-side CORS proxy with host allowlist + SSRF guards
- `GET /api/health` — liveness + catalog stats

## Quick start

```bash
pip install -r requirements.txt
python parse_catalog.py   # optional refresh from upstream README
gunicorn app:app --bind 0.0.0.0:5000
```

Open http://localhost:5000

## Proxy usage (for bots / browser tools)

Only hostnames that appear in catalog links (and their subdomains) are allowed. Private IPs, localhost, and cloud metadata endpoints are blocked. Timeout ~15s, ~2MB size limit, light per-IP rate limit.

```bash
# Example: CoinPaprika tickers via the hub proxy
curl "https://YOUR-SERVICE.onrender.com/api/proxy?url=$(python -c 'import urllib.parse;print(urllib.parse.quote("https://api.coinpaprika.com/v1/tickers", safe=""))')"
```

From a New Bot / agent:

```
GET {HUB_BASE}/api/proxy?url={urlencoded_https_target}
```

Optional headers forwarded: `Authorization`, `X-Api-Key`.

## Deploy

- GitHub: `sweater9/public-apis-hub`
- Render: Python 3.12, `pip install -r requirements.txt`, start `gunicorn app:app --bind 0.0.0.0:$PORT`, free, Singapore

## Data

`catalog.json` is generated from the upstream README sections **Blockchain** and **Cryptocurrency** only (v1). Fields: `api`, `description`, `auth`, `https`, `cors`, `link`, `category`.
