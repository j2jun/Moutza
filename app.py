"""Moutza: share and search resources about universities and organizations.

Stdlib only. Run: python3 app.py [port]  ->  http://localhost:8000
"""
import html
import math
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

DB_PATH = "moutza.db"
LIMITS = {"title": 200, "url": 500, "school": 100, "tags": 200, "description": 2000}
REQUIRED = ("title", "url", "school")
MAX_BODY = 10_000


def connect(path=DB_PATH):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL, url TEXT NOT NULL, school TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))""")
    return db


def validate(form):
    """Return (clean data, list of error messages)."""
    data = {k: form.get(k, "").strip() for k in LIMITS}
    errors = [f"{k} is required" for k in REQUIRED if not data[k]]
    errors += [f"{k} is too long (max {n})" for k, n in LIMITS.items() if len(data[k]) > n]
    u = urlparse(data["url"])
    if data["url"] and (u.scheme not in ("http", "https") or not u.netloc):
        errors.append("url must start with http:// or https://")
    return data, errors


def add_resource(db, data):
    cur = db.execute(
        "INSERT INTO resources (title, url, school, tags, description) VALUES (?,?,?,?,?)",
        tuple(data[k] for k in LIMITS))
    db.commit()
    return cur.lastrowid


# --- search: TF-IDF cosine similarity -------------------------------------
# ponytail: re-scores every row per query (O(n)); move to SQLite FTS5 past ~10k rows.

def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def doc_text(row):
    # Title counted twice so title matches outrank description matches.
    return " ".join((row["title"], row["title"], row["school"], row["tags"], row["description"]))


def rank(rows, query):
    """Rows sorted by relevance to query; rows with no overlap are dropped."""
    docs = [Counter(tokens(doc_text(r))) for r in rows]
    df = Counter(t for d in docs for t in d)
    idf = {t: math.log((len(docs) + 1) / (df[t] + 1)) + 1 for t in df}

    def vec(c):
        return {t: n * idf.get(t, 0) for t, n in c.items()}

    q = vec(Counter(tokens(query)))
    q_norm = math.sqrt(sum(v * v for v in q.values())) or 1
    scored = []
    for row, d in zip(rows, docs):
        v = vec(d)
        dot = sum(w * v.get(t, 0) for t, w in q.items())
        if dot > 0:
            scored.append((dot / (q_norm * math.sqrt(sum(x * x for x in v.values()))), row))
    scored.sort(key=lambda s: -s[0])
    return [row for _, row in scored]


def similar(rows, target, n=3):
    return [r for r in rank(rows, doc_text(target)) if r["id"] != target["id"]][:n]


# --- HTML ------------------------------------------------------------------

e = lambda s: html.escape(str(s), quote=True)

CSS = """body{font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:0 auto;padding:16px;
color:#1d2433;background:#fafafa}a{color:#2952cc;overflow-wrap:anywhere}header{display:flex;justify-content:space-between;
align-items:center;flex-wrap:wrap;gap:8px}h1 a{text-decoration:none;color:inherit}form.search{display:flex;gap:8px;
flex-wrap:wrap}input,select,textarea{font:inherit;padding:6px 8px;border:1px solid #ccd;
border-radius:6px}input[name=q]{flex:1;min-width:160px}textarea{width:100%;min-height:90px}
label{display:block;margin-top:10px;font-weight:600}label input{width:100%;box-sizing:border-box}
button{font:inherit;padding:6px 14px;border:0;border-radius:6px;background:#2952cc;color:#fff;
cursor:pointer}.card{background:#fff;border:1px solid #e3e5ea;border-radius:8px;padding:12px;
margin:12px 0}.meta{color:#667;font-size:14px}.err{color:#b00020}
@media (prefers-color-scheme:dark){body{background:#14171f;color:#e4e6eb}.card{background:#1d212b;
border-color:#2c313d}a{color:#8fb0ff}input,select,textarea{background:#1d212b;color:inherit;
border-color:#394050}.meta{color:#99a}}"""


def page(title, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>{CSS}</style></head><body><header><h1><a href="/">Moutza</a></h1>
<a href="/add">+ Share a resource</a></header>{body}</body></html>"""


def card(r):
    tags = f" · {e(r['tags'])}" if r["tags"] else ""
    return f"""<div class="card"><a href="/r/{r['id']}"><strong>{e(r['title'])}</strong></a>
<div class="meta">{e(r['school'])}{tags}</div><div>{e(r['description'][:200])}</div></div>"""


def add_form(data=None, errors=()):
    data = data or {}
    errs = "".join(f'<p class="err">{e(m)}</p>' for m in errors)
    fields = "".join(
        f'<label>{k.title()}{" *" if k in REQUIRED else ""}'
        f'<input name="{k}" value="{e(data.get(k, ""))}" maxlength="{LIMITS[k]}"></label>'
        for k in ("title", "url", "school", "tags"))
    return page("Share a resource", f"""<h2>Share a resource</h2>{errs}
<form method="post" action="/add">{fields}
<label>Description<textarea name="description" maxlength="{LIMITS['description']}">{e(data.get('description', ''))}</textarea></label>
<p><button>Share</button></p></form>""")


# --- HTTP ------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    db_path = DB_PATH

    def send(self, status, body="", headers=()):
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        with closing(connect(self.db_path)) as db:
            if url.path == "/":
                return self.send(200, self.index(db, params.get("q", "").strip(), params.get("school", "")))
            if url.path == "/add":
                return self.send(200, add_form())
            m = re.fullmatch(r"/r/(\d+)", url.path)
            row = m and db.execute("SELECT * FROM resources WHERE id=?", (int(m[1]),)).fetchone()
            if row:
                return self.send(200, self.detail(db, row))
        self.send(404, page("Not found", "<p>Not found.</p>"))

    def do_POST(self):
        if urlparse(self.path).path != "/add":
            return self.send(404, page("Not found", "<p>Not found.</p>"))
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self.send(413, page("Too large", "<p>Submission too large.</p>"))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", "replace")).items()}
        data, errors = validate(form)
        if errors:
            return self.send(400, add_form(data, errors))
        with closing(connect(self.db_path)) as db:
            rid = add_resource(db, data)
        self.send(303, headers=[("Location", f"/r/{rid}")])

    def index(self, db, q, school):
        rows = db.execute(
            "SELECT * FROM resources WHERE ?='' OR school=? ORDER BY id DESC", (school, school)).fetchall()
        if q:
            rows = rank(rows, q)
        schools = [r[0] for r in db.execute("SELECT DISTINCT school FROM resources ORDER BY school")]
        opts = "".join(f'<option{" selected" if s == school else ""}>{e(s)}</option>' for s in schools)
        heading = f"{len(rows)} result(s) for “{e(q)}”" if q else "Latest resources"
        results = "".join(map(card, rows)) or "<p>Nothing here yet. <a href='/add'>Share the first one.</a></p>"
        return page("Moutza", f"""<form class="search" action="/">
<input name="q" value="{e(q)}" placeholder="Search scholarships, clubs, housing…" aria-label="Search">
<select name="school" aria-label="School"><option value="">All schools</option>{opts}</select>
<button>Search</button></form><h2>{heading}</h2>{results}""")

    def detail(self, db, row):
        rows = db.execute("SELECT * FROM resources").fetchall()
        rel = "".join(map(card, similar(rows, row))) or "<p class='meta'>None yet.</p>"
        school_link = f"/?school={quote(row['school'])}"
        return page(row["title"], f"""<div class="card"><h2>{e(row['title'])}</h2>
<p><a href="{e(row['url'])}" rel="noopener noreferrer nofollow" target="_blank">{e(row['url'])}</a></p>
<p class="meta"><a href="{e(school_link)}">{e(row['school'])}</a>
{(' · ' + e(row['tags'])) if row['tags'] else ''} · shared {e(row["created"][:10])}</p>
<p>{e(row['description'])}</p></div><h3>Similar resources</h3>{rel}""")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Moutza on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
