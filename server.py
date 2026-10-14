#!/usr/bin/env python3
"""
MiDAS web portal — one FastAPI app serving the UI (static/) + the live pipeline API.
Single origin (no CORS). In-memory TTL cache + bounded inputs so a public endpoint can't
hammer EuropePMC/ENA. Run locally:  uvicorn server:app --port 8080  (then open http://localhost:8080)
Deploy: see DEPLOY.md (App Runner / Lightsail).
"""
import os, sys, csv, time, re
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import discover as D          # stage 1-2 (EuropePMC search + accession extraction)
import ingest as I            # stage 3 (ENA structured hydration) -> I.draft(acc)

app = FastAPI(title="MiDAS", docs_url="/api/docs", redoc_url=None)

# ---- tiny in-memory TTL cache (keeps a public endpoint from re-hitting ENA/EuropePMC) ----
_CACHE = {}
def cached(key, ttl, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val

def load_catalog():
    path = os.path.join(HERE, "datasets_hydrated.tsv")
    if not os.path.exists(path):
        path = os.path.join(HERE, "datasets.tsv")
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    for r in rows:                                   # prefer computed strain_capable
        if r.get("strain_capable_hydrated"):
            r["strain_capable"] = r["strain_capable_hydrated"]
    return rows

@app.get("/api/health")
def health():
    return {"ok": True, "datasets": len(cached("catalog", 300, load_catalog))}

@app.get("/api/datasets")
def datasets():
    return cached("catalog", 300, load_catalog)

@app.get("/api/discover")
def discover(q: str = Query(..., min_length=3, max_length=120),
             n: int = Query(10, ge=1, le=15)):
    """Stage 1-2: question -> papers -> accessions, flagged new vs already-cataloged."""
    def run():
        papers = D.search(q, n)
        known = D.known_accessions()
        acc2papers, out = {}, []
        for p in papers:
            accs = D.accessions_for(p)
            prj = sorted(a for a in accs if D.PRJ.match(a))
            ref = (p.get("authorString", "")[:18] + " " + str(p.get("pubYear", ""))).strip()
            for a in prj:
                acc2papers.setdefault(a, []).append(ref)
            out.append({"title": (p.get("title") or "")[:150], "year": p.get("pubYear", ""),
                        "journal": p.get("journalTitle", ""), "oa": p.get("isOpenAccess") == "Y",
                        "accessions": prj})
        return {"query": q, "papers": out,
                "new_accessions": sorted(a for a in acc2papers if a not in known),
                "cataloged": sorted(a for a in acc2papers if a in known)}
    return cached("disc:%s:%d" % (q.lower(), n), 3600, run)

@app.get("/api/ingest")
def ingest(accession: str = Query(..., pattern=r"^PRJ[EN][AB]\d+$")):
    """Stage 3: live ENA hydration of one BioProject into a draft row."""
    def run():
        d = I.draft(accession)
        if not d:
            raise HTTPException(404, "no runs found for %s" % accession)
        return d
    return cached("ing:%s" % accession, 3600, run)

# ---- contact form -> email via SES ----------------------------------------
CONTACT_TO   = os.environ.get("MIDAS_CONTACT_TO", "you@example.com")   # override at deploy via MIDAS_CONTACT_TO
CONTACT_FROM = os.environ.get("MIDAS_CONTACT_FROM", "MiDAS <noreply@nuwaslab.com>")
SES_REGION   = os.environ.get("MIDAS_SES_REGION", "us-east-1")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TOPICS = {"question": "Question", "feature": "Feature request", "other": "Other"}

class ContactForm(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    topic: str = Field(default="question", max_length=40)
    message: str = Field(min_length=1, max_length=4000)
    website: str = Field(default="", max_length=200)   # honeypot: real users leave it blank

# per-IP sliding-window rate limit (in-memory; per instance — fine for low traffic)
_RL = {}
def _rate_ok(ip, limit=5, window=600):
    now = time.time()
    hits = [t for t in _RL.get(ip, []) if now - t < window]
    if len(hits) >= limit:
        _RL[ip] = hits
        return False
    hits.append(now)
    _RL[ip] = hits
    return True

@app.post("/api/contact")
def contact(form: ContactForm, request: Request):
    if form.website.strip():                       # honeypot tripped -> accept silently, drop
        return {"ok": True}
    email = form.email.strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Please enter a valid email address.")
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?")
    if not _rate_ok(ip):
        raise HTTPException(429, "Too many messages from your network — please try again shortly.")
    topic = _TOPICS.get(form.topic, "Message")
    subject = "[MiDAS] %s from %s" % (topic, form.name[:60])
    body = ("New MiDAS contact submission\n\n"
            "Topic:   %s\nName:    %s\nEmail:   %s\nSource:  %s\n\nMessage:\n%s\n"
            % (topic, form.name, email, ip, form.message))
    try:
        import boto3
        boto3.client("sesv2", region_name=SES_REGION).send_email(
            FromEmailAddress=CONTACT_FROM,
            Destination={"ToAddresses": [CONTACT_TO]},
            ReplyToAddresses=[email],
            Content={"Simple": {"Subject": {"Data": subject},
                                "Body": {"Text": {"Data": body}}}})
    except Exception as e:                          # don't leak internals to the client
        print("contact send failed:", repr(e), file=sys.stderr)
        raise HTTPException(502, "Couldn't send your message right now — please try again later.")
    return {"ok": True}

@app.get("/gut")
def gut_page():
    """Gut MGE / resistome prototype resolver (clean URL for static/gut.html)."""
    return FileResponse(os.path.join(HERE, "static", "gut.html"))

@app.get("/hiv")
def hiv_page():
    """HIV / SIV gut prototype resolver (clean URL for static/hiv.html)."""
    return FileResponse(os.path.join(HERE, "static", "hiv.html"))

# static UI last (catch-all mount); /api/* above take precedence
app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True), name="ui")
