#!/usr/bin/env python3
"""
MiDAS cross-repository metadata indexing (roadmap item, stage 1).

MiDAS resolves a seeded catalog; this module lets one question reach *across* the public microbiome
repositories and answer the field's hardest question: **which datasets actually carry the metadata I
need** (disease, host age, diet, antibiotics, body site, ...), normalized so the same field means the
same thing across repos.

Design:
  * Each repository is an `Adapter` that emits the normalized `Dataset` record below (the same shape as
    MiDAS's catalog: body sites, assay, access, n, and a *canonical* metadata-field set).
  * `CANON_METADATA` is a MIxS-lite controlled vocabulary: it maps each repo's heterogeneous field names
    to shared canonical keys, so "which datasets have `diet` + `disease`" works across sources.
  * `cross_search(query, need=[...])` fans out to the adapters, normalizes, and keeps the datasets whose
    metadata covers `need`.

Stage 1 ships the framework + the MGnify adapter (open REST, rich per-sample metadata). NMDC (API
confirmed), ENA (already used by MiDAS for depth), cMD (via R export) and Qiita (redbiom) are drop-in
next — see docs/crossrepo.md. Stdlib only (urllib + json), like the rest of MiDAS.
"""
from __future__ import annotations
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict

UA = {"User-Agent": "MiDAS-crossrepo/0.1 (+https://midas.nuwaslab.com)"}

# --------------------------------------------------------------------------- canonical metadata vocab

# canonical key -> phrases that, as whole words in a repo's field name, signal the field is present.
# Deliberately conservative; this is the honest MIxS-lite layer, not a finished ontology.
CANON_METADATA = {
    "disease":        ["disease", "diagnosis", "diagnoses", "dx", "health state", "study condition",
                       "disease status", "ibd", "case control", "subject health"],
    "host_age":       ["age", "host age", "age years", "age at collection"],
    "sex":            ["sex", "gender"],
    "bmi":            ["bmi", "body mass index"],
    "diet":           ["diet", "dietary", "food", "nutrition", "hei", "ffq", "feeding", "breastfed"],
    "antibiotics":    ["antibiotic", "antibiotics", "abx", "antimicrobial"],
    "treatment":      ["treatment", "medication", "therapy", "drug exposure"],
    "country":        ["country", "geo loc name", "geographic location", "nation"],
    "collection_date":["collection date", "sampling date", "date of collection"],
    "timepoint":      ["visit", "timepoint", "longitudinal", "day of", "week of", "trimester"],
    "body_site":      ["body site", "isolation source", "env material", "environment material",
                       "sample type", "body product", "env broad scale", "env local scale"],
    "host_species":   ["host taxid", "host tax id", "host species", "host organism",
                       "host common name", "host scientific name"],
    "ph":             ["ph"],
    "smoking":        ["smoking", "tobacco", "smoker"],
    "subject_id":     ["subject", "individual", "patient", "participant"],
}

_COMPILED = {k: [re.compile(r"\b" + re.escape(s) + r"\b") for s in syns]
             for k, syns in CANON_METADATA.items()}


def _clean(key: str) -> str:
    return re.sub(r"\s+", " ", str(key).lower().replace("_", " ").replace("-", " ")).strip()


def normalize_metadata(raw_keys) -> set:
    """Map a repo's raw field names to the canonical metadata key set they cover."""
    out = set()
    for raw in raw_keys:
        kl = _clean(raw)
        for canon, pats in _COMPILED.items():
            if any(p.search(kl) for p in pats):
                out.add(canon)
    return out


def coverage(have: set, need) -> bool:
    """True if the dataset's canonical metadata set covers every requested field."""
    return set(need).issubset(have)


# --------------------------------------------------------------------------- normalized record

@dataclass
class Dataset:
    source_repo: str
    accession: str
    title: str = ""
    url: str = ""
    host: str = "unknown"                 # human | environmental | mouse | unknown
    body_sites: list = field(default_factory=list)
    assay_types: list = field(default_factory=list)   # 16S | shotgun | unknown
    n_samples: int = 0
    access: str = "open"                  # open | controlled | request-only (MiDAS tri-state)
    metadata_fields: set = field(default_factory=set) # canonical keys present
    raw_metadata_keys: list = field(default_factory=list)
    strain_capable: str = "compute"       # defer to MiDAS depth computation
    extra: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        d = asdict(self)
        d["body_sites"] = ";".join(self.body_sites)
        d["assay_types"] = ";".join(self.assay_types)
        d["metadata_fields"] = ";".join(sorted(self.metadata_fields))
        d["raw_metadata_keys"] = ";".join(self.raw_metadata_keys[:40])
        d.pop("extra", None)
        return d


# --------------------------------------------------------------------------- HTTP + adapter base

def get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class Adapter:
    name = "base"

    def search(self, query: str, limit: int = 5, timeout: int = 30) -> list:
        raise NotImplementedError


# --------------------------------------------------------------------------- MGnify adapter

class MGnify(Adapter):
    """EBI MGnify (metagenomics). Open REST JSON:API; per-sample metadata is key/value attributes."""
    name = "mgnify"
    API = "https://www.ebi.ac.uk/metagenomics/api/v1"
    # biome lineages worth special-casing from a gut/human query
    GUT_LINEAGE = "root:Host-associated:Human:Digestive system"

    def search(self, query: str, limit: int = 5, timeout: int = 30) -> list:
        q = query.lower()
        params = {"page_size": str(max(limit, 5))}
        if any(w in q for w in ("gut", "stool", "faecal", "fecal", "digestive", "intestin")):
            params["lineage"] = self.GUT_LINEAGE
        else:
            params["search"] = query
        url = f"{self.API}/studies?" + urllib.parse.urlencode(params)
        try:
            data = get_json(url, timeout).get("data", [])
        except Exception:
            # search param can 400 on some deployments; fall back to the human-gut lineage
            url = f"{self.API}/studies?" + urllib.parse.urlencode(
                {"page_size": str(max(limit, 5)), "lineage": self.GUT_LINEAGE})
            data = get_json(url, timeout).get("data", [])
        out = []
        for st in data[:limit]:
            out.append(self._study_to_dataset(st, timeout))
        return out

    def _study_to_dataset(self, st: dict, timeout: int) -> Dataset:
        a = st.get("attributes", {})
        acc = a.get("accession", st.get("id", ""))
        ds = Dataset(
            source_repo=self.name, accession=acc,
            title=a.get("study-name", "") or a.get("study-abstract", "")[:120],
            url=f"https://www.ebi.ac.uk/metagenomics/studies/{acc}",
            n_samples=int(a.get("samples-count") or 0), access="open",
            extra={"bioproject": a.get("bioproject")},
        )
        self._hydrate_samples(ds, acc, timeout)
        return ds

    def _hydrate_samples(self, ds: Dataset, acc: str, timeout: int, k: int = 10):
        """Aggregate metadata keys + host/body-site across up to k samples of the study."""
        try:
            url = f"{self.API}/studies/{acc}/samples?" + urllib.parse.urlencode({"page_size": str(k)})
            samples = get_json(url, timeout).get("data", [])
        except Exception:
            return
        raw_keys, hosts, sites = set(), set(), set()
        for s in samples:
            sa = s.get("attributes", {})
            # structured attributes that are themselves metadata fields
            for key in ("collection-date", "geo-loc-name", "environment-biome",
                        "environment-feature", "environment-material", "host-tax-id", "species"):
                if sa.get(key) not in (None, "", "not collected", "not provided"):
                    raw_keys.add(key)
            # the free key/value sample-metadata list
            for kv in sa.get("sample-metadata", []) or []:
                if kv.get("key"):
                    raw_keys.add(kv["key"])
            tax = str(sa.get("host-tax-id") or "")
            sp = str(sa.get("species") or "").lower()
            if tax == "9606" or "homo sapiens" in sp or "human" in sp:
                hosts.add("human")
            for sitey in (sa.get("environment-material"), sa.get("environment-feature"),
                          sa.get("environment-biome")):
                if sitey and sitey not in ("not collected", "not provided"):
                    sites.add(str(sitey))
        ds.raw_metadata_keys = sorted(raw_keys)
        ds.metadata_fields = normalize_metadata(raw_keys)
        ds.host = "human" if "human" in hosts else ("environmental" if sites else "unknown")
        ds.body_sites = sorted(sites)[:4]


# --------------------------------------------------------------------------- registry + cross search

ADAPTERS = {MGnify.name: MGnify()}


def cross_search(query: str, need=(), repos=("mgnify",), limit: int = 5, timeout: int = 30) -> list:
    """Fan out `query` to the chosen repo adapters, normalize, and keep datasets whose metadata covers
    `need` (a list of canonical keys). Returns a list of Dataset."""
    need = [n.strip() for n in need if n and n.strip()]
    results = []
    for rp in repos:
        ad = ADAPTERS.get(rp)
        if not ad:
            continue
        try:
            found = ad.search(query, limit=limit, timeout=timeout)
        except Exception as e:  # a repo being down must not sink the whole search
            print(f"[warn] {rp}: {str(e)[:80]}", file=sys.stderr)
            continue
        for ds in found:
            if not need or coverage(ds.metadata_fields, need):
                results.append(ds)
    # rank: most metadata-rich and largest first
    results.sort(key=lambda d: (len(d.metadata_fields), d.n_samples), reverse=True)
    return results


# --------------------------------------------------------------------------- CLI

def _main(argv) -> int:
    import argparse
    try:  # non-ASCII safe on a cp1252 Windows console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="crossrepo",
        description="MiDAS cross-repository metadata search: which public datasets carry the metadata you need.")
    p.add_argument("query", nargs="?", default="human gut microbiome",
                   help="free-text question/terms (e.g. 'human gut microbiome')")
    p.add_argument("--need", default="", help="comma-separated canonical metadata fields the dataset must carry "
                   "(e.g. disease,host_age,diet). Options: " + ",".join(CANON_METADATA))
    p.add_argument("--repos", default="mgnify", help="comma-separated: " + ",".join(ADAPTERS))
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    need = [x for x in a.need.split(",") if x.strip()]
    repos = [x.strip() for x in a.repos.split(",") if x.strip()]
    res = cross_search(a.query, need=need, repos=repos, limit=a.limit)
    if a.json:
        print(json.dumps([d.to_row() for d in res], indent=2)); return 0
    print("=" * 76)
    print(f"MiDAS cross-repo — '{a.query}'" + (f"  | need: {', '.join(need)}" if need else ""))
    print("=" * 76)
    if not res:
        print("  no datasets matched (try fewer --need fields, or a broader query)"); return 0
    for d in res:
        print(f"\n  [{d.source_repo}] {d.accession}  ({d.host}, n={d.n_samples}, {d.access})")
        print(f"    {d.title[:70]}")
        if d.body_sites:
            print(f"    sites: {', '.join(d.body_sites)[:66]}")
        print(f"    metadata: {', '.join(sorted(d.metadata_fields)) or '(none normalized)'}")
    print(f"\n[{len(res)} dataset(s)]  {d.url if res else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
