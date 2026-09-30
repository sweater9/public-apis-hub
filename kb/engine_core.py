"""KB FTS core: ensure_index, search, get_doc, status."""
from __future__ import annotations
import re, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "kb.sqlite"
CORPUS = ROOT / "kb" / "corpus"
_STOP = set("a an the is are was were be been being to of in on for and or as at by with from that this it its into about what how why when where who which can does do did me my your you i we they their our".split())

def ensure_index(force: bool = False) -> bool:
    """Build FTS index if missing, empty, or corpus file count drifted."""
    corpus_n = len(list(CORPUS.glob("*.md"))) if CORPUS.is_dir() else 0

    def usable() -> bool:
        if not (DB_PATH.is_file() and DB_PATH.stat().st_size > 0):
            return False
        try:
            c = _connect()
            n = c.execute("SELECT COUNT(*) AS c FROM docs").fetchone()["c"]
            c.close()
            if n <= 0:
                return False
            # Rebuild when corpus grew/shrank vs indexed docs
            if corpus_n and n != corpus_n:
                return False
            return True
        except Exception:
            return False

    if not force and usable():
        return True
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
        except OSError:
            pass
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_kb_index", ROOT / "scripts" / "build_kb_index.py")
    if not spec or not spec.loader:
        return False
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    try:
        return mod.build() == 0 and usable()
    except Exception as exc:
        print(f"kb index build failed: {exc}"); return False

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def status() -> dict:
    ok = DB_PATH.is_file(); doc_count = chunk_count = 0
    if ok:
        try:
            c = _connect(); doc_count = c.execute("SELECT COUNT(*) AS c FROM docs").fetchone()["c"]
            chunk_count = c.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]; c.close()
        except Exception as exc:
            return {"ok": False, "index_ok": False, "doc_count": 0, "chunk_count": 0, "db_path": str(DB_PATH.relative_to(ROOT)), "error": str(exc)}
    corpus_n = len(list(CORPUS.glob("*.md"))) if CORPUS.is_dir() else 0
    return {"ok": ok and doc_count > 0, "index_ok": ok and doc_count > 0, "doc_count": doc_count, "chunk_count": chunk_count, "corpus_files": corpus_n, "db_path": str(DB_PATH.relative_to(ROOT)) if ok else None, "mode": "offline-corpus"}

def _fts_query(q: str) -> str:
    tokens = [t for t in re.findall(r"[A-Za-z0-9_+\-]+", q.lower()) if t not in _STOP and len(t) > 1]
    if not tokens:
        tokens = re.findall(r"[A-Za-z0-9_+\-]+", q.lower()) or ["crypto"]
    parts = []
    for t in tokens[:8]:
        safe = t.replace(chr(34), "")
        if len(safe) >= 3:
            parts.append(chr(34) + safe + chr(34) + "*")
        else:
            parts.append(chr(34) + safe + chr(34))
    return " AND ".join(parts)

def search(q: str, limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit or 20), 50)); q = (q or "").strip()
    if not q: return []
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT d.slug,d.title,d.category,d.tags,d.path,snippet(docs_fts,3,'','',' ... ',24) AS snip,bm25(docs_fts) AS score FROM docs_fts JOIN docs d ON d.id=docs_fts.rowid WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts) LIMIT ?",
            (_fts_query(q), limit),
        ).fetchall()
    except sqlite3.OperationalError:
        toks = re.findall(r"[A-Za-z0-9_+\-]+", q.lower())
        fts2_parts = [chr(34) + t.replace(chr(34), "") + chr(34) for t in toks[:8]]
        fts2 = " OR ".join(fts2_parts) or (chr(34) + "crypto" + chr(34))
        rows = conn.execute(
            "SELECT d.slug,d.title,d.category,d.tags,d.path,snippet(docs_fts,3,'','',' ... ',24) AS snip,bm25(docs_fts) AS score FROM docs_fts JOIN docs d ON d.id=docs_fts.rowid WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts) LIMIT ?",
            (fts2, limit),
        ).fetchall()
    conn.close()
    return [{"title": r["title"], "slug": r["slug"], "path": r["path"], "tags": [t.strip() for t in (r["tags"] or "").split(",") if t.strip()], "category": r["category"], "snippet": (r["snip"] or "").replace("\n", " ").strip(), "score": round(-float(r["score"]), 4)} for r in rows]

def get_doc(slug: str) -> dict | None:
    slug = (slug or "").strip()
    if not slug or "/" in slug or ".." in slug: return None
    conn = _connect(); row = conn.execute("SELECT slug,title,category,tags,path,body FROM docs WHERE slug=?", (slug,)).fetchone(); conn.close()
    if not row: return None
    from kb.ask_engine import md_to_html
    return {"slug": row["slug"], "title": row["title"], "category": row["category"], "tags": [t.strip() for t in (row["tags"] or "").split(",") if t.strip()], "path": row["path"], "markdown": row["body"], "html": md_to_html(row["body"])}

def _query_terms(q: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_+\-]+", q.lower()) if t not in _STOP and len(t) > 1]

def _score_chunk(text: str, terms: list[str]) -> float:
    low = text.lower(); score = sum(low.count(t)*(2.0 if len(t)>4 else 1.0) for t in terms)
    if any(x in low[:120] for x in (" means ", " is ", " are ", " refers ")): score += 1.5
    if text.lstrip().startswith("#"): score -= 0.5
    return score

def _clean_chunk(text: str) -> str:
    lines=[]
    for line in text.splitlines():
        if line.startswith("#"): continue
        lines.append(line)
    cleaned=[]
    for x in lines:
        x=x.strip()
        if not x: continue
        if x.startswith("- "): x=x[2:].strip()
        cleaned.append(x)
    s=" ".join(cleaned); s=re.sub(r"\s+", " ", s).strip(); s=re.sub(r"\*\*([^*]+)\*\*", r"\1", s); s=re.sub(r"`([^`]+)`", r"\1", s)
    return s
