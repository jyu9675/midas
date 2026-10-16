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
import os
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
                       "sample type", "body product", "env broad scale", "env local scale",
                       "env medium", "habitat", "ecosystem", "collection site"],
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


# --------------------------------------------------------------------------- NMDC adapter

def _nmdc_val(v):
    """NMDC stores many fields as nested value objects, e.g.
    {"has_raw_value": "...", "term": {"name": "..."}}. Return the most human-readable scalar."""
    if isinstance(v, dict):
        term = v.get("term") or {}
        return term.get("name") or v.get("has_raw_value") or ""
    return v


class NMDC(Adapter):
    """National Microbiome Data Collaborative. Open REST; biosamples carry MIxS/ENVO metadata and link to
    studies via `associated_studies`. Environmental-heavy (soil/water/engineered), but adds breadth."""
    name = "nmdc"
    API = "https://api.microbiomedata.org"
    _VALUE_KEYS = ("collection_date", "geo_loc_name", "env_broad_scale", "env_local_scale",
                   "env_medium", "habitat", "ecosystem", "ecosystem_category",
                   "sample_collection_site", "lat_lon", "depth", "ncbi_taxonomy_name")

    def search(self, query: str, limit: int = 5, timeout: int = 30) -> list:
        studies = get_json(f"{self.API}/studies?per_page=100", timeout).get("results", [])
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]

        def score(st):
            hay = " ".join(str(st.get(k, "")) for k in
                           ("name", "title", "description", "ecosystem", "ecosystem_category",
                            "ecosystem_type", "specific_ecosystem")).lower()
            return sum(1 for t in terms if t in hay)

        matched = sorted((s for s in studies if score(s) > 0), key=score, reverse=True)
        return [self._study_to_dataset(st, timeout) for st in matched[:limit]]

    def _study_to_dataset(self, st: dict, timeout: int) -> Dataset:
        sid = st.get("id", "")
        ds = Dataset(source_repo=self.name, accession=sid,
                     title=(st.get("title") or st.get("name") or "")[:120],
                     url=f"https://data.microbiomedata.org/details/study/{sid}", access="open",
                     extra={"ecosystem": st.get("ecosystem")})
        self._hydrate(ds, sid, timeout)
        return ds

    def _hydrate(self, ds: Dataset, sid: str, timeout: int, k: int = 10):
        try:
            bs = get_json(f"{self.API}/biosamples?per_page={k}&filter=associated_studies:{sid}", timeout)
        except Exception:
            return
        ds.n_samples = int((bs.get("meta") or {}).get("count") or 0)
        raw, sites, human = set(), set(), False
        for b in bs.get("results", []):
            for key in self._VALUE_KEYS:
                if b.get(key):
                    raw.add(key)
            for key in ("env_medium", "env_local_scale", "env_broad_scale", "habitat",
                        "sample_collection_site"):
                val = _nmdc_val(b.get(key))
                if val and not str(val).startswith("ENVO:"):
                    sites.add(str(val))
            tax = str(b.get("ncbi_taxonomy_name") or "").lower()
            eco = " ".join(str(b.get(x, "")) for x in ("ecosystem", "ecosystem_category", "ecosystem_type")).lower()
            if "homo sapiens" in tax or "human" in eco:
                human = True
        ds.raw_metadata_keys = sorted(raw)
        ds.metadata_fields = normalize_metadata(raw)
        ds.host = "human" if human else ("environmental" if sites else "unknown")
        ds.body_sites = sorted(sites)[:4]


# --------------------------------------------------------------------------- ENA adapter

class ENA(Adapter):
    """EBI/ENA via the Portal API. Human metagenomic read_runs grouped to studies. ENA's structured
    sample fields are frequently empty/'missing' — which is itself the honest metadata-coverage signal."""
    name = "ena"
    PORTAL = "https://www.ebi.ac.uk/ena/portal/api/search"
    _SITE = {"gut": "feces", "stool": "feces", "faecal": "feces", "fecal": "feces",
             "vagina": "vagina", "vaginal": "vagina", "oral": "oral mucosa", "skin": "skin", "nasal": "nasal"}
    _EMPTY = {"", "missing", "not collected", "not provided", "n/a", "na", "none", "unknown"}
    _FIELDS = ("study_accession,sample_accession,study_title,library_strategy,"
               "host_body_site,collection_date,country,host_sex,host_tax_id")

    def search(self, query: str, limit: int = 5, timeout: int = 30) -> list:
        q = query.lower()
        base = ['tax_tree(9606)', 'library_source="METAGENOMIC"']
        site = next((v for k, v in self._SITE.items() if k in q), None)
        # try site-filtered first (precision); fall back unfiltered since ENA's body-site field is sparse
        for cons in ([base + [f'host_body_site="{site}"']] if site else []) + [base]:
            params = {"result": "read_run", "query": " AND ".join(cons),
                      "fields": self._FIELDS, "limit": str(limit * 40), "format": "json"}
            # ENA's portal requires %20 for spaces in `query`, not urlencode's default '+'
            qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            try:
                runs = get_json(self.PORTAL + "?" + qs, timeout)
            except Exception:
                runs = []
            studies = {}
            for r in runs if isinstance(runs, list) else []:
                sa = r.get("study_accession")
                if sa:
                    studies.setdefault(sa, []).append(r)
            if studies:
                return [self._study(sa, rs) for sa, rs in list(studies.items())[:limit]]
        return []

    def _study(self, sa: str, rs: list) -> Dataset:
        raw, sites, strat = set(), set(), set()
        for r in rs:
            for key in ("collection_date", "country", "host_body_site", "host_sex", "host_tax_id"):
                v = str(r.get(key) or "").strip()
                if v and v.lower() not in self._EMPTY:
                    raw.add(key)
            bs = str(r.get("host_body_site") or "").strip()
            if bs and bs.lower() not in self._EMPTY:
                sites.add(bs)
            if r.get("library_strategy"):
                strat.add(r["library_strategy"].upper())
        assay = []
        joined = " ".join(strat)
        if "WGS" in joined or "METAGENOM" in joined or "OTHER" in joined:
            assay.append("shotgun")
        if "AMPLICON" in joined:
            assay.append("16S")
        ds = Dataset(source_repo=self.name, accession=sa,
                     title=(rs[0].get("study_title") or "")[:120],
                     url=f"https://www.ebi.ac.uk/ena/browser/view/{sa}", host="human", access="open",
                     n_samples=len({r.get("sample_accession") for r in rs}),
                     assay_types=assay or ["unknown"])
        ds.raw_metadata_keys = sorted(raw)
        ds.metadata_fields = normalize_metadata(raw)
        ds.body_sites = sorted(sites)[:4]
        return ds


# --------------------------------------------------------------------------- dbGaP adapter (discovery)

class dbGaP(Adapter):
    """NCBI dbGaP via E-utilities. Controlled access: sample/phenotype metadata is GOVERNED and not
    fetchable without authorization, so this adapter is discovery-only — it finds studies and marks them
    `controlled` with the application link. `metadata_fields` is intentionally empty (governed)."""
    name = "dbgap"
    EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def search(self, query: str, limit: int = 5, timeout: int = 30) -> list:
        term = urllib.parse.quote(query)
        try:
            es = get_json(f"{self.EUTILS}/esearch.fcgi?db=gap&term={term}&retmax={limit}&retmode=json", timeout)
            ids = es.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []
            summ = get_json(f"{self.EUTILS}/esummary.fcgi?db=gap&id={','.join(ids)}&retmode=json", timeout)
        except Exception:
            return []
        res = summ.get("result", {})
        out = []
        for uid in res.get("uids", []):
            r = res.get(uid, {})
            title = (r.get("d_study_name") or r.get("title") or r.get("summary")
                     or f"dbGaP record {uid}")
            acc = r.get("accession") or r.get("d_study_id") or uid
            out.append(Dataset(
                source_repo=self.name, accession=str(acc), title=str(title)[:120],
                url=f"https://www.ncbi.nlm.nih.gov/gap/?term={term}",
                host="unknown", access="controlled", n_samples=0,
                raw_metadata_keys=["(governed — apply via dbGaP)"], metadata_fields=set(),
                extra={"note": "dbGaP sample/phenotype metadata is controlled; discovery only"}))
        return out[:limit]


# --------------------------------------------------------------------------- curatedMetagenomicData

class CMD(Adapter):
    """curatedMetagenomicData — the richest *harmonized human* metadata, but R-package data with no clean
    no-auth download. This adapter reads a local `sampleMetadata` TSV EXPORT (set MIDAS_CMD_TSV, or pass
    `tsv=`); `write_cmd_export_R()` emits the one-line R script that produces it. Groups by study_name and
    reports each column that is populated as a metadata field."""
    name = "cmd"

    def __init__(self, tsv: str | None = None):
        self.tsv = tsv or os.environ.get("MIDAS_CMD_TSV", "")

    def search(self, query: str, limit: int = 5, timeout: int = 30) -> list:
        import csv
        if not self.tsv or not os.path.exists(self.tsv):
            return []
        with open(self.tsv, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        if not rows:
            return []
        cols = list(rows[0].keys())
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        studies = {}
        for r in rows:
            sn = r.get("study_name") or r.get("studyID") or "unknown_study"
            studies.setdefault(sn, []).append(r)
        out = []
        for sn, rs in studies.items():
            hay = (sn + " " + " ".join(str(rs[0].get(c, "")) for c in
                   ("body_site", "disease", "study_condition", "country"))).lower()
            if terms and not any(t in hay for t in terms):
                continue
            present = {c for c in cols if any(str(rr.get(c) or "").strip() not in ("", "NA")
                                              for rr in rs[:50])}
            ds = Dataset(source_repo=self.name, accession=sn, title=sn,
                         url="https://waldronlab.io/curatedMetagenomicData/", host="human",
                         access="open", n_samples=len(rs), assay_types=["shotgun"])
            ds.raw_metadata_keys = sorted(present)
            ds.metadata_fields = normalize_metadata(present)
            ds.body_sites = sorted({str(rr.get("body_site")) for rr in rs if rr.get("body_site")})[:4]
            out.append(ds)
        out.sort(key=lambda d: (len(d.metadata_fields), d.n_samples), reverse=True)
        return out[:limit]


def write_cmd_export_R(out_path: str) -> str:
    """Emit the one-line R that exports cMD's harmonized sampleMetadata to the TSV this adapter reads."""
    script = ('#!/usr/bin/env Rscript\n'
              '# install once: BiocManager::install("curatedMetagenomicData")\n'
              'suppressMessages(library(curatedMetagenomicData))\n'
              'write.table(sampleMetadata, "cmd_sampleMetadata.tsv", sep = "\\t",\n'
              '            quote = FALSE, row.names = FALSE)\n'
              '# then: MIDAS_CMD_TSV=cmd_sampleMetadata.tsv python crossrepo.py "<q>" --repos cmd\n')
    with open(out_path, "w", newline="\n", encoding="utf-8") as fh:
        fh.write(script)
    return out_path


# --------------------------------------------------------------------------- Qiita (redbiom) — scaffold

class Qiita(Adapter):
    """Qiita, via redbiom (metadata/feature search over Qiita + EMP). redbiom needs a reachable context
    server (env REDBIOM_HOST, default the public UCSD one). It was NOT reachable from this build
    environment, so this adapter is a documented scaffold: it returns [] gracefully rather than fabricate
    redbiom's wire format. Much Qiita content is also deposited to ENA/EBI, which the ENA/MGnify adapters
    already index. To finish live: implement the redbiom metadata-category query against a reachable host
    and normalize its sample-metadata categories through `normalize_metadata` (same as every adapter)."""
    name = "qiita"
    HOST = os.environ.get("REDBIOM_HOST", "https://redbiom.ucsd.edu")

    def search(self, query: str, limit: int = 5, timeout: int = 30) -> list:
        return []   # honest no-op until a reachable redbiom context is wired (see docstring)


# --------------------------------------------------------------------------- registry + cross search

ADAPTERS = {MGnify.name: MGnify(), NMDC.name: NMDC(), ENA.name: ENA(),
            dbGaP.name: dbGaP(), CMD.name: CMD(), Qiita.name: Qiita()}


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
