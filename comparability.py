#!/usr/bin/env python3
"""
MiDAS resolve-time comparability score ("move C" of the metadata-reuse roadmap).

Batch-correction tools (ConQuR, MMUPHin) operate *after* you've already committed to pooling studies.
This flips that: at *discovery* time, given two datasets (the normalized `Dataset` records the cross-repo
adapters produce), estimate **whether they can be pooled/compared at all, and how** — before any download
or compute. It combines:

  * metadata overlap  — do they both carry the fields the question needs?
  * alignment gates   — host, body site, and assay must match for a like-with-like comparison; a
                        mismatch here (gut vs vaginal, 16S vs shotgun) can't be rescued by metadata.
  * batch-effect risk — a conservative estimate from provenance (same uniformly-processed repo = lower;
                        cross-repo pipelines = high), with the correction method to reach for.

Output is a poolability score (0-1), the per-dimension subscores, the *limiting factor*, a batch-risk
level + recommended correction, and honest caveats. Deliberately interpretable, not a trained model.
Works on `crossrepo.Dataset` objects or plain dicts. Stdlib only.
"""
from __future__ import annotations

try:
    from metaqc import canon_site               # reuse the body-site canonicalizer
except Exception:                                # pragma: no cover
    def canon_site(x): return ""

# repos whose data is UNIFORMLY reprocessed (lower technical batch within the repo)
_UNIFORM = {"cmd", "mgnify"}


def _get(ds, attr, default=None):
    return getattr(ds, attr, None) if not isinstance(ds, dict) else ds.get(attr, default)


def _as_set(x):
    if not x:
        return set()
    if isinstance(x, (set, list, tuple)):
        return set(x)
    return {s.strip() for s in str(x).split(";") if s.strip()}


def _canon_sites(ds):
    sites = _as_set(_get(ds, "body_sites"))
    return {canon_site(s) for s in sites if canon_site(s)}


def _assay_kind(ds):
    a = " ".join(_as_set(_get(ds, "assay_types"))).lower()
    if "shotgun" in a or "metagenom" in a or "wgs" in a:
        return "shotgun"
    if "16s" in a or "amplicon" in a:
        return "16S"
    return "unknown"


def _metadata_overlap(a, b, need):
    ma, mb = _as_set(_get(a, "metadata_fields")), _as_set(_get(b, "metadata_fields"))
    if need:
        need = set(need)
        shared = need & ma & mb
        return (len(shared) / len(need) if need else 0.0,
                {"needed": sorted(need), "both_have": sorted(shared),
                 "missing_in_a": sorted(need - ma), "missing_in_b": sorted(need - mb)})
    union = ma | mb
    return (len(ma & mb) / len(union) if union else 0.0,
            {"both_have": sorted(ma & mb), "a_only": sorted(ma - mb), "b_only": sorted(mb - ma)})


def _match(sa, sb, good=1.0, bad=0.0, unknown=0.5):
    if not sa or not sb or "unknown" in (sa, sb):
        return unknown
    return good if sa == sb else bad


def _assay_score(a, b):
    ka, kb = _assay_kind(a), _assay_kind(b)
    if "unknown" in (ka, kb):
        return 0.5
    if ka == kb == "shotgun":
        return 1.0
    if ka == kb == "16S":
        return 0.7                               # same assay, but 16S region may still differ
    return 0.2                                    # 16S vs shotgun: different feature spaces


def _body_site_score(a, b):
    ca, cb = _canon_sites(a), _canon_sites(b)
    if not ca or not cb:
        return 0.5
    return 1.0 if (ca & cb) else 0.0              # any shared canonical site


def batch_risk(a, b) -> dict:
    """Conservative technical-batch-effect estimate from provenance."""
    ra, rb = (_get(a, "source_repo") or "").lower(), (_get(b, "source_repo") or "").lower()
    if ra == rb and ra in _UNIFORM:
        level, why = "medium", f"same uniformly-processed repo ({ra}); residual per-study effects remain"
    elif ra == rb and ra:
        level, why = "medium-high", f"same repo ({ra}) but not uniformly reprocessed; per-study protocols differ"
    else:
        level, why = "high", f"cross-repo ({ra or '?'} vs {rb or '?'}): different processing pipelines"
    return {"level": level, "why": why,
            "recommend": "treat each study as a batch; correct with ConQuR or MMUPHin before pooling"}


def compare(a, b, need=()) -> dict:
    """Score how poolable datasets `a` and `b` are. `need` = canonical metadata fields the question
    requires (optional). Returns poolability (0-1), subscores, the limiting factor, batch risk, verdict."""
    host = _match((_get(a, "host") or "unknown"), (_get(b, "host") or "unknown"))
    site = _body_site_score(a, b)
    assay = _assay_score(a, b)
    meta, meta_detail = _metadata_overlap(a, b, need)

    gates = {"host_match": host, "body_site_match": site, "assay_match": assay}
    pool = host * site * assay * (0.5 + 0.5 * meta)   # gates dominate; metadata modulates, can't rescue

    # limiting factor = the dimension holding the score down
    dims = {**gates, "metadata_overlap": meta}
    limiting = min(dims, key=dims.get)
    risk = batch_risk(a, b)

    if pool >= 0.7:
        verdict = "High — directly poolable"
    elif pool >= 0.4:
        verdict = f"Moderate — comparable with care (limited by {limiting.replace('_', ' ')})"
    elif pool >= 0.15:
        verdict = f"Low — limited comparability (limited by {limiting.replace('_', ' ')})"
    else:
        verdict = f"Not comparable (blocked by {limiting.replace('_', ' ')})"

    return {
        "a": _get(a, "accession"), "b": _get(b, "accession"),
        "poolability": round(pool, 2), "verdict": verdict, "limiting_factor": limiting,
        "subscores": {**{k: round(v, 2) for k, v in gates.items()}, "metadata_overlap": round(meta, 2)},
        "metadata": meta_detail, "batch_risk": risk,
        "caveat": "Alignment gates (host/body-site/assay) are reliable; metadata_overlap depends on the "
                  "coverage layer; platform-level batch risk is conservative when platform is unrecorded.",
    }


def rank_comparable(target, candidates, need=()) -> list:
    """Rank `candidates` by poolability to `target` (most comparable first)."""
    scored = [(compare(target, c, need), c) for c in candidates]
    scored.sort(key=lambda t: t[0]["poolability"], reverse=True)
    return scored
