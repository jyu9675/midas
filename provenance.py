#!/usr/bin/env python3
"""
MiDAS provenance / trust-tiered metadata records ("move B" — the connective tissue of the
metadata-reuse roadmap).

Every existing tool flattens a metadata value to present/absent with no record of where it came from or
how reliable it is. That is the meta-problem underneath missing/inconsistent metadata. Here, every value
carries `(value, source, method, confidence)`, so the resolver can answer "which datasets carry disease
status *as a curated field*" vs "...including values inferred from the data, confidence > 0.8" — and the
same container holds the move-A triangulation (deposited vs inferred) as first-class provenance.

Trust tiers (high → low):
  curated   — hand-curated (e.g. curatedMetagenomicData)         default conf 0.95
  deposited — from the repository's structured submission        default conf 0.80
  extracted — pulled from text by an LLM/NER                     default conf 0.60
  inferred  — computed from the data itself (e.g. metaqc)        confidence supplied by the inference

A field can hold several entries from different sources; `best()` applies tier-then-confidence, and
`triangulate()` reports whether the sources agree (corroborated) or conflict (likely error — move A).
Stdlib only; integrates with `crossrepo.Dataset` and `metaqc`.
"""
from __future__ import annotations
from dataclasses import dataclass, field as _dc_field, asdict

try:
    from metaqc import canon_site
except Exception:                                 # pragma: no cover
    def canon_site(x): return str(x or "").strip().lower()

TRUST_TIERS = {"curated": 4, "deposited": 3, "extracted": 2, "inferred": 1}
DEFAULT_CONF = {"curated": 0.95, "deposited": 0.80, "extracted": 0.60, "inferred": 0.50}


@dataclass
class MetaField:
    field: str                   # canonical key (disease, host_age, body_site, ...)
    value: str                   # the value ("" if only presence is known)
    source: str                  # origin: cmd | mgnify | ena | dbgap | nmdc | paper | taxonomy | ...
    method: str                  # curated | deposited | extracted | inferred
    confidence: float = 0.0

    def tier(self) -> int:
        return TRUST_TIERS.get(self.method, 0)


class ProvenancedMetadata:
    """Canonical field -> list of MetaField (one per contributing source)."""

    def __init__(self):
        self._by_field: dict[str, list] = {}

    def add(self, field: str, value: str = "", source: str = "", method: str = "deposited",
            confidence: float | None = None) -> "ProvenancedMetadata":
        if method not in TRUST_TIERS:
            raise ValueError(f"unknown method {method!r}; use one of {list(TRUST_TIERS)}")
        conf = DEFAULT_CONF[method] if confidence is None else float(confidence)
        self._by_field.setdefault(field, []).append(
            MetaField(field=field, value=str(value or ""), source=source, method=method, confidence=conf))
        return self

    def best(self, field: str):
        """Highest-trust entry for a field: tier first, then confidence."""
        entries = self._by_field.get(field, [])
        return max(entries, key=lambda m: (m.tier(), m.confidence)) if entries else None

    def fields(self, min_method: str = "inferred", min_confidence: float = 0.0) -> set:
        """Canonical fields with at least one entry at or above `min_method` tier and `min_confidence`.
        This is the trust-filtered coverage set the resolver / comparability `need` check consumes."""
        floor = TRUST_TIERS[min_method]
        return {f for f, es in self._by_field.items()
                if any(m.tier() >= floor and m.confidence >= min_confidence for m in es)}

    def triangulate(self, field: str) -> dict:
        """Do the sources for a field agree? 'single' (one source), 'agree' (corroborated), or
        'conflict' (likely error — surfaces move A as provenance)."""
        es = self._by_field.get(field, [])
        if len(es) < 2:
            return {"field": field, "status": "single", "entries": [asdict(m) for m in es]}
        norm = canon_site if field == "body_site" else (lambda v: str(v or "").strip().lower())
        vals = {norm(m.value) for m in es if m.value}
        status = "agree" if len(vals) <= 1 else "conflict"
        note = ("one source only" if status == "single" else
                "sources corroborate" if status == "agree" else
                "sources disagree — likely mislabeled/inconsistent; review")
        return {"field": field, "status": status, "distinct_values": sorted(vals),
                "entries": [asdict(m) for m in es], "note": note}

    def records(self) -> list:
        return [asdict(m) for es in self._by_field.values() for m in es]

    def to_rows(self) -> list:
        """Flat rows: one per (field, source) — for a provenance table / export."""
        return [{"field": m.field, "value": m.value, "source": m.source,
                 "method": m.method, "confidence": round(m.confidence, 3)}
                for es in self._by_field.values() for m in es]


# --------------------------------------------------------------------------- bridges

def _get(ds, attr, default=None):
    return getattr(ds, attr, None) if not isinstance(ds, dict) else ds.get(attr, default)


def from_dataset(ds) -> ProvenancedMetadata:
    """Build a provenanced record from a crossrepo.Dataset (or dict): each canonical field it reports
    becomes a 'curated' entry for cMD, else 'deposited', sourced to the repo. Body site gets its value."""
    pm = ProvenancedMetadata()
    repo = (_get(ds, "source_repo") or "").lower()
    method = "curated" if repo == "cmd" else "deposited"
    mf = _get(ds, "metadata_fields") or set()
    fields = mf if isinstance(mf, (set, list, tuple)) else {s for s in str(mf).split(";") if s}
    sites = _get(ds, "body_sites") or []
    site_val = (sites[0] if isinstance(sites, (list, tuple)) and sites else str(sites or ""))
    for f in fields:
        pm.add(f, value=(site_val if f == "body_site" else ""), source=repo or "repo", method=method)
    return pm


def add_inference(pm: ProvenancedMetadata, field: str, value: str, confidence: float,
                  source: str = "taxonomy") -> ProvenancedMetadata:
    """Attach a value computed from the data (e.g. metaqc's inferred body site) as an 'inferred' entry.
    Combined with an existing deposited entry, `triangulate(field)` then flags agree/conflict."""
    return pm.add(field, value=value, source=source, method="inferred", confidence=confidence)
