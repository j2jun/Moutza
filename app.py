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
LABELS = {"title": "Title", "url": "Link", "school": "School", "tags": "Tags", "description": "Description"}
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
    errors = [f"{LABELS[k]} is required" for k in REQUIRED if not data[k]]
    errors += [f"{LABELS[k]} is too long (max {n} characters)" for k, n in LIMITS.items() if len(data[k]) > n]
    u = urlparse(data["url"])
    if data["url"] and (u.scheme not in ("http", "https") or not u.netloc):
        errors.append("Link must start with http:// or https://")
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


def rank(rows, query, min_score=0.0):
    """Rows sorted by relevance to query; rows scoring <= min_score are dropped."""
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
        score = dot / (q_norm * math.sqrt(sum(x * x for x in v.values())) or 1)
        if score > min_score:
            scored.append((score, row))
    scored.sort(key=lambda s: -s[0])
    return [row for _, row in scored]


def similar(rows, target, n=3):
    # ponytail: 0.08 cutoff tuned on sample data (real matches >=0.12, shared-school noise <=0.05); retune as data grows.
    return [r for r in rank(rows, doc_text(target), min_score=0.08) if r["id"] != target["id"]][:n]


# --- HTML ------------------------------------------------------------------

e = lambda s: html.escape(str(s), quote=True)

FONT = "https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800&display=swap"

CSS = """
:root{--cork:#d8b47f;--cork-dot:#c59c62;--ink:#1e2747;--board-ink:#2b1d0e;--pin:#e23e57;
--p0:#fff27a;--p1:#bdf2d0;--p2:#ffc4d3;--p3:#b9dcff;--p4:#fffdf5;--card:#fffdf5;--rule:#c9dcf2;--margin:#f2a7b4}
@media (prefers-color-scheme:dark){:root{--cork:#3a2b1c;--cork-dot:#4b3825;--board-ink:#f3e3c7}
.btn:not(.alt){background:var(--p0);color:var(--ink)}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;color:var(--ink);font:17px/1.5 "Bricolage Grotesque",system-ui,sans-serif;
background:var(--cork) radial-gradient(var(--cork-dot) 1.2px,transparent 1.6px) 0 0/9px 9px}
.wrap{max-width:1040px;margin:0 auto;padding:20px 16px 64px}
a{color:inherit;overflow-wrap:anywhere}
:focus-visible{outline:3px solid var(--pin);outline-offset:3px}
header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;margin-bottom:8px}
.logo{display:inline-block;padding:4px 22px 6px;font-size:clamp(34px,7vw,56px);font-weight:800;letter-spacing:-.03em;
line-height:1;text-decoration:none;background:rgba(255,250,228,.88);transform:rotate(-2.5deg);
box-shadow:0 3px 8px -4px rgba(0,0,0,.4);clip-path:polygon(0 6%,3% 0,97% 4%,100% 0,99% 94%,96% 100%,2% 96%,0 100%)}
.tagline{margin:14px 0 22px;max-width:34em;color:var(--board-ink);font-size:18px}
.btn{display:inline-block;font:inherit;font-weight:700;padding:9px 18px;border:2px solid var(--ink);border-radius:10px;
background:var(--ink);color:var(--p0);text-decoration:none;cursor:pointer;box-shadow:3px 3px 0 var(--pin);
transition:transform .12s,box-shadow .12s}
.btn:hover{transform:translate(-1px,-1px);box-shadow:4px 4px 0 var(--pin)}
.btn:active{transform:translate(2px,2px);box-shadow:1px 1px 0 var(--pin)}
.btn.alt{background:var(--p4);color:var(--ink)}
.index-card{position:relative;background:var(--card);padding:22px 20px 20px 44px;border-radius:3px;
background-image:linear-gradient(90deg,transparent 30px,var(--margin) 30px,var(--margin) 32px,transparent 32px),
repeating-linear-gradient(transparent 0 27px,var(--rule) 27px 28px);box-shadow:0 12px 22px -12px rgba(40,20,0,.55)}
.search{display:flex;flex-wrap:wrap;gap:10px;align-items:center;max-width:760px}
input,select,textarea{font:inherit;color:var(--ink);padding:8px 10px;border:2px solid var(--ink);border-radius:8px;background:#fff}
.search input{flex:1 1 220px}
h2.board{color:var(--board-ink);font-size:26px;font-weight:800;letter-spacing:-.01em;margin:36px 0 18px}
.flyers{columns:240px;column-gap:26px}
.flyer{position:relative;break-inside:avoid;display:inline-block;width:100%;margin:12px 0 22px;padding:26px 18px 16px;
background:var(--p4);transform:rotate(var(--r));box-shadow:0 1px 0 rgba(0,0,0,.08),0 14px 18px -10px rgba(40,20,0,.55);
transition:transform .18s ease,box-shadow .18s ease;animation:pin .5s cubic-bezier(.2,1.4,.4,1) both;animation-delay:calc(var(--i)*70ms)}
.flyer::before{content:"";position:absolute;top:8px;left:50%;width:16px;height:16px;margin-left:-8px;border-radius:50%;
background:radial-gradient(circle at 35% 35%,#fff8 0 2px,var(--pin) 3px);box-shadow:1px 3px 3px rgba(0,0,0,.35)}
.flyer:hover,.flyer:focus-within{transform:rotate(0) translateY(-4px) scale(1.02);box-shadow:0 22px 26px -14px rgba(40,20,0,.6);z-index:1}
.flyer h3{margin:0 0 4px;font-size:21px;line-height:1.2;font-weight:800;letter-spacing:-.01em}
.flyer h3 a{text-decoration:none}
.flyer h3 a::after{content:"";position:absolute;inset:0}
.school{margin:0 0 8px;font-size:14px;font-weight:600;opacity:.75}
.flyer p{margin:0 0 10px}
.p0{background:var(--p0)}.p1{background:var(--p1)}.p2{background:var(--p2)}.p3{background:var(--p3)}
.tags{display:flex;flex-wrap:wrap;gap:6px}
.tag{position:relative;z-index:1;font-size:13px;font-weight:600;padding:1px 9px;border:1.5px solid var(--ink);border-radius:999px;
background:rgba(255,255,255,.55);text-decoration:none}
a.tag:hover{background:var(--ink);color:var(--p0)}
@keyframes pin{from{opacity:0;transform:translateY(-26px) rotate(calc(var(--r)*-3))}}
.big{display:block;max-width:620px;margin:28px auto 0;padding:40px 30px 0;animation:none}
.big h1{margin:0 0 6px;font-size:clamp(30px,6vw,46px);line-height:1.05;letter-spacing:-.025em;font-weight:800}
.big .desc{font-size:19px;max-width:34em}
.big .meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:14px 0 18px}
.url{font-size:14px;opacity:.75}
.tabs{display:flex;margin:24px -30px 0;border-top:2px dashed rgba(30,39,71,.45)}
.tabs a{flex:1;min-height:120px;padding:10px 0;border-right:2px dashed rgba(30,39,71,.3);writing-mode:vertical-rl;
font-size:13px;font-weight:700;text-decoration:none;display:flex;align-items:center;justify-content:flex-start;transition:transform .15s}
.tabs a:last-child{border-right:0}
.tabs a:hover{transform:translateY(6px) rotate(3deg);background:rgba(255,255,255,.35)}
.hint{text-align:center;color:var(--board-ink);font-size:15px;margin:10px 0 0}
.empty{color:var(--board-ink);font-size:19px}
.empty a{font-weight:700}
form.pin label{display:block;margin:0 0 14px;font-weight:700}
form.pin label small{font-weight:400;opacity:.7}
form.pin input,form.pin textarea{display:block;width:100%;margin-top:4px}
form.pin textarea{min-height:110px}
.pinform{max-width:620px;margin:28px auto 0}
.pinform h1{margin:0 0 16px;font-size:34px;font-weight:800;letter-spacing:-.02em}
.err{margin:0 0 16px;padding:10px 14px;background:var(--p2);border-left:5px solid var(--pin);font-weight:600}
.err p{margin:0}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def page(title, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONT}"><style>{CSS}</style></head><body><div class="wrap">
<header><a class="logo" href="/">Moutza</a><nav><a class="btn" href="/add">Pin a flyer</a></nav></header>
{body}</div></body></html>"""


def tag_list(r):
    return [t.strip() for t in r["tags"].split(",") if t.strip()]


def tilt(r):
    """Stable -1.8..1.8 degree tilt per flyer so the board looks hand-pinned."""
    return ((r["id"] * 37) % 7 - 3) * 0.6


def paper(r):
    """Paper color from the first tag, so flyers on the same topic match."""
    first = (tag_list(r) or [r["school"]])[0].lower()
    return sum(map(ord, first)) % 5


def card(r, i=0):
    desc = r["description"]
    desc = desc if len(desc) <= 160 else desc[:157].rstrip() + "…"
    tags = "".join(f'<span class="tag">{e(t)}</span>' for t in tag_list(r))
    return f"""<article class="flyer p{paper(r)}" style="--r:{tilt(r)}deg;--i:{min(i, 12)}">
<h3><a href="/r/{r['id']}">{e(r['title'])}</a></h3><p class="school">{e(r['school'])}</p>
{f'<p>{e(desc)}</p>' if desc else ''}<div class="tags">{tags}</div></article>"""


def board(rows):
    return '<div class="flyers">' + "".join(card(r, i) for i, r in enumerate(rows)) + "</div>"


def add_form(data=None, errors=()):
    data = data or {}
    errs = f'<div class="err" role="alert">{"".join(f"<p>{e(m)}</p>" for m in errors)}</div>' if errors else ""
    hints = {"url": "https://…", "tags": "comma separated, e.g. scholarship, housing", "school": "university or organization"}

    def field(k):
        req = " required" if k in REQUIRED else ""
        hint = f" <small>{hints[k]}</small>" if k in hints else ""
        return (f'<label>{LABELS[k]}{hint}<input name="{k}" value="{e(data.get(k, ""))}" '
                f'maxlength="{LIMITS[k]}"{req}{" type=url" if k == "url" else ""}></label>')

    return page("Pin a flyer · Moutza", f"""<div class="index-card pinform"><h1>Pin a flyer</h1>{errs}
<form class="pin" method="post" action="/add">{"".join(field(k) for k in ("title", "url", "school", "tags"))}
<label>Description <small>what's inside, and who it's for</small><textarea name="description" maxlength="{LIMITS['description']}">{e(data.get('description', ''))}</textarea></label>
<button class="btn">Pin it</button></form></div>""")


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


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

    def not_found(self):
        self.send(404, page("Not found · Moutza", """<h2 class="board">That flyer fell off the board.</h2>
<p class="empty"><a href="/">Back to the board</a></p>"""))

    def do_GET(self):
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        with closing(connect(self.db_path)) as db:
            if url.path == "/":
                return self.send(200, self.index(db, params.get("q", "").strip(), params.get("school", "")))
            if url.path == "/add":
                return self.send(200, add_form())
            if url.path == "/random":
                row = db.execute("SELECT id FROM resources ORDER BY RANDOM() LIMIT 1").fetchone()
                return self.send(303, headers=[("Location", f"/r/{row['id']}" if row else "/add")])
            m = re.fullmatch(r"/r/(\d+)", url.path)
            row = m and db.execute("SELECT * FROM resources WHERE id=?", (int(m[1]),)).fetchone()
            if row:
                return self.send(200, self.detail(db, row))
        self.not_found()

    def do_POST(self):
        if urlparse(self.path).path != "/add":
            return self.not_found()
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self.send(413, page("Too large · Moutza", '<h2 class="board">That flyer is too big to pin. Shorten the description and try again.</h2>'))
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
        if q:
            heading = f"{plural(len(rows), 'flyer')} {'matches' if len(rows) == 1 else 'match'} “{e(q)}”"
        else:
            heading = f"Pinned at {e(school)}" if school else "Fresh on the board"
        if rows:
            results = board(rows)
        elif q:
            results = '<p class="empty">Try a shorter word, or <a href="/add">pin the flyer you were looking for</a>.</p>'
        else:
            results = '<p class="empty">Nothing pinned here yet. <a href="/add">Pin the first flyer</a>.</p>'
        return page("Moutza", f"""<p class="tagline">The campus bulletin board for scholarships, clubs, housing,
and everything your school forgot to tell you.</p>
<form class="search index-card" action="/">
<input name="q" value="{e(q)}" placeholder="Search scholarships, clubs, housing…" aria-label="Search the board">
<select name="school" aria-label="School"><option value="">All schools</option>{opts}</select>
<button class="btn">Search</button><a class="btn alt" href="/random">Surprise me</a></form>
<h2 class="board">{heading}</h2>{results}""")

    def detail(self, db, row):
        rows = db.execute("SELECT * FROM resources").fetchall()
        rel = similar(rows, row)
        host = urlparse(row["url"]).netloc
        link = f'href="{e(row["url"])}" target="_blank" rel="noopener noreferrer nofollow"'
        tabs = "".join(
            f'<a {link} aria-label="Open {e(host)}">{e(host)}</a>' if i == 0
            else f'<a {link} tabindex="-1" aria-hidden="true">{e(host)}</a>' for i in range(6))
        tags = "".join(f'<a class="tag" href="/?q={quote(t)}">{e(t)}</a>' for t in tag_list(row))
        nearby = f'<h2 class="board">Pinned nearby</h2>{board(rel)}' if rel else ""
        return page(f"{row['title']} · Moutza", f"""<article class="flyer big p{paper(row)}" style="--r:{tilt(row) / 2}deg;--i:0">
<h1>{e(row['title'])}</h1>
<div class="meta"><a class="tag" href="/?school={quote(row['school'])}">{e(row['school'])}</a>{tags}</div>
{f'<p class="desc">{e(row["description"])}</p>' if row["description"] else ''}
<p class="url">Pinned {e(row["created"][:10])} · {e(row["url"])}</p>
<nav class="tabs" aria-label="Open the link">{tabs}</nav></article>
<p class="hint">Tear off a tab to open the link.</p>{nearby}""")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Moutza on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
