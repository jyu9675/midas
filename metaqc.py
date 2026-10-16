#!/usr/bin/env python3
"""
MiDAS metadata QC by triangulation (prototype — "move A" of the metadata-reuse roadmap).

The field's hard problem isn't only *missing* metadata — it's *untrustworthy* metadata (mislabeled
samples, inconsistent fields). The under-explored idea here: don't just scrape the deposited label,
**cross-check it against what the data itself implies**. For body site this is strong, because the
taxonomic signature predicts body site very reliably (published shotgun classifiers exceed 99%), so a
*disagreement* between the deposited body site and the taxonomy is a reliable red flag for a
mislabeled / mixed sample — and an *agreement* is positive corroboration.

This module:
  * `infer_body_site(abund)`   — a transparent, specificity-weighted body-site classifier from a
                                 genus→abundance profile (no black box; every call shows its evidence).
  * `triangulate_body_site(...)` — compare the DEPOSITED body site against the INFERRED one and return a
                                 verdict (agree / conflict / inferred-only / …) with a confidence and the
                                 genera that drove it. This is the provenance-aware record "move B" seeds.
  * `mgnify_genus_profile(...)` — optional: pull a real genus profile from MGnify to triangulate live.

Deliberately rule-based and interpretable: a mislabel audit has to be defensible, and (per the
"ML-metadata predictors often fail to generalize" caution) a legible classifier with an **abstention**
rule beats an opaque one here. Stdlib only.
"""
from __future__ import annotations
import json
import sys
import urllib.request

# Canonical body-site genus signatures. Genera are listed under the site(s) where they are
# *characteristic*; multi-site genera (e.g. Prevotella) are down-weighted automatically by specificity,
# so they don't dominate a call. Not exhaustive — a reviewable starting panel.
BODY_SITE_SIGNATURES = {
    "vaginal": ["Lactobacillus", "Gardnerella", "Atopobium", "Fannyhessea", "Sneathia", "Megasphaera",
                "Mobiluncus", "Prevotella", "Bifidobacterium"],
    "gut":     ["Bacteroides", "Phocaeicola", "Faecalibacterium", "Ruminococcus", "Blautia", "Roseburia",
                "Collinsella", "Akkermansia", "Eubacterium", "Bifidobacterium", "Prevotella", "Alistipes"],
    "oral":    ["Streptococcus", "Veillonella", "Neisseria", "Fusobacterium", "Rothia", "Haemophilus",
                "Porphyromonas", "Actinomyces", "Prevotella"],
    "skin":    ["Cutibacterium", "Propionibacterium", "Staphylococcus", "Corynebacterium", "Micrococcus"],
    "nasal":   ["Corynebacterium", "Staphylococcus", "Moraxella", "Dolosigranulum", "Haemophilus"],
}

# free-text / ENVO-ish deposited body-site -> canonical key
_CANON = {
    "vagina": "vaginal", "vaginal": "vaginal", "posterior fornix": "vaginal", "cervix": "vaginal",
    "cervicovaginal": "vaginal", "introitus": "vaginal",
    "feces": "gut", "faeces": "gut", "stool": "gut", "gut": "gut", "intestine": "gut", "intestinal": "gut",
    "fecal": "gut", "rectal": "gut", "rectum": "gut", "colon": "gut", "digestive": "gut",
    "oral": "oral", "saliva": "oral", "mouth": "oral", "tongue": "oral", "dental": "oral", "buccal": "oral",
    "subgingival": "oral", "supragingival": "oral",
    "skin": "skin", "dermal": "skin", "forearm": "skin",
    "nasal": "nasal", "nares": "nasal", "nose": "nasal", "nostril": "nasal",
}

# precompute how many sites each genus appears in (for specificity weighting)
_SITES_PER_GENUS: dict[str, int] = {}
for _site, _gs in BODY_SITE_SIGNATURES.items():
    for _g in _gs:
        _SITES_PER_GENUS[_g] = _SITES_PER_GENUS.get(_g, 0) + 1


def canon_site(text: str) -> str:
    """Map a deposited body-site string to a canonical key (vaginal/gut/oral/skin/nasal) or ''."""
    t = str(text or "").lower()
    for k, v in _CANON.items():
        if k in t:
            return v
    return ""


def infer_body_site(abund: dict, min_signal: float = 0.10, min_margin: float = 0.15) -> dict:
    """Infer body site from a genus→abundance mapping (counts or relative abundance).

    Score per site = sum over that site's signature genera of (relative abundance × specificity weight),
    where specificity weight = 1 / (number of sites that list the genus) — so a ubiquitous marker like
    Prevotella counts less than a specific one like Faecalibacterium. Returns the predicted site with a
    confidence and the genera that drove it; **abstains** ('uncertain'/'ambiguous') when too little
    signature signal is present or the top two sites are too close.
    """
    total = sum(v for v in abund.values() if v and v > 0) or 1.0
    rel = {g: (v / total) for g, v in abund.items() if v and v > 0}
    scores, evidence = {}, {}
    for site, genera in BODY_SITE_SIGNATURES.items():
        s, ev = 0.0, []
        for g in genera:
            a = rel.get(g, 0.0)
            if a > 0:
                w = 1.0 / _SITES_PER_GENUS[g]
                s += a * w
                ev.append((g, round(a, 4)))
        scores[site] = s
        evidence[site] = sorted(ev, key=lambda x: -x[1])[:4]
    ssum = sum(scores.values())
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top_site, top_raw = ranked[0]
    norm = {k: (v / ssum if ssum else 0.0) for k, v in scores.items()}
    margin = norm[ranked[0][0]] - (norm[ranked[1][0]] if len(ranked) > 1 else 0.0)
    if top_raw < min_signal:
        call = "uncertain"
    elif margin < min_margin:
        call = "ambiguous"
    else:
        call = top_site
    return {"site": call, "confidence": round(norm.get(top_site, 0.0), 3),
            "margin": round(margin, 3), "signal": round(top_raw, 3),
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "evidence": evidence.get(top_site, [])}


def triangulate_body_site(deposited: str, abund: dict, **kw) -> dict:
    """Cross-check a deposited body site against the taxonomy-inferred one. Verdicts:
    agree · conflict (likely mislabeled/mixed) · inferred_only (fills a gap) · deposited_only
    (can't corroborate) · uninformative. Carries method + confidence (provenance-aware record)."""
    inf = infer_body_site(abund, **kw)
    dep_canon = canon_site(deposited)
    confident = inf["site"] in BODY_SITE_SIGNATURES
    if dep_canon and confident:
        verdict = "agree" if dep_canon == inf["site"] else "conflict"
    elif dep_canon and not confident:
        verdict = "deposited_only"
    elif not dep_canon and confident:
        verdict = "inferred_only"
    else:
        verdict = "uninformative"
    note = {"agree": "taxonomy corroborates the deposited body site",
            "conflict": "taxonomy disagrees with the deposited label — likely mislabeled or mixed; review",
            "inferred_only": "deposited body site missing — filled from taxonomy (flagged inferred)",
            "deposited_only": "taxonomy inconclusive — deposited label kept, uncorroborated",
            "uninformative": "neither deposited nor taxonomy gives a confident body site"}[verdict]
    return {"verdict": verdict, "deposited": deposited or "", "deposited_canon": dep_canon or "",
            "inferred_site": inf["site"], "inferred_confidence": inf["confidence"],
            "method": "taxonomy-signature (specificity-weighted)", "evidence": inf["evidence"],
            "note": note}


# --------------------------------------------------------------------------- optional live MGnify pull

def mgnify_genus_profile(study_accession: str, timeout: int = 30) -> dict:
    """Pull a genus→count profile for a MGnify study's first analysis (SSU taxonomy). Network; best-effort."""
    api = "https://www.ebi.ac.uk/metagenomics/api/v1"
    def _get(u):
        req = urllib.request.Request(u, headers={"Accept": "application/json",
                                                 "User-Agent": "MiDAS-metaqc/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    analyses = _get(f"{api}/studies/{study_accession}/analyses?page_size=1").get("data", [])
    if not analyses:
        return {}
    aid = analyses[0]["id"]
    tax = _get(f"{api}/analyses/{aid}/taxonomy/ssu?page_size=200").get("data", [])
    prof = {}
    for t in tax:
        a = t.get("attributes", {})
        genus = (a.get("hierarchy") or {}).get("genus")
        if genus and a.get("count"):
            prof[genus] = prof.get(genus, 0) + int(a["count"])
    return prof


def _main(argv) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not argv:
        print("usage: python metaqc.py <MGnify study accession> [deposited_body_site]\n"
              "  e.g. python metaqc.py MGYS00006849 'human gut'")
        return 1
    acc = argv[0]
    deposited = argv[1] if len(argv) > 1 else "human gut"   # MGnify gut-lineage default
    prof = mgnify_genus_profile(acc)
    if not prof:
        print(f"no genus profile for {acc}")
        return 1
    v = triangulate_body_site(deposited, prof)
    print("=" * 66)
    print(f"MiDAS metadata QC — {acc}")
    print("=" * 66)
    print(f"  deposited body site : {v['deposited']}  (canon: {v['deposited_canon'] or '—'})")
    print(f"  inferred body site  : {v['inferred_site']}  (conf {v['inferred_confidence']}, {v['method']})")
    print(f"  top genera          : {', '.join(f'{g} {a}' for g, a in v['evidence'])}")
    print(f"  VERDICT             : {v['verdict'].upper()} — {v['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
