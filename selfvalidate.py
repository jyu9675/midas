#!/usr/bin/env python3
"""
MiDAS self-validated inference with abstention ("move D" — the capstone of the metadata-reuse roadmap).

A benchmark warns that ML metadata predictors often *fail to generalize — worse than a naive baseline*.
So MiDAS never trusts an inferred field on faith. The protocol here:

  1. Split a cohort into *labeled* (the field was deposited = ground truth) and *unlabeled* (missing).
  2. Run the inference on the LABELED subset and **measure** it: accuracy, non-abstention coverage, and —
     crucially — whether it **beats the majority-class naive baseline** (the exact bar the caution sets).
  3. Only if it clears the bar do we apply it to the unlabeled subset, and the emitted values carry the
     **measured accuracy** as their confidence (not a hand-set number) — which flows straight into the
     move-B provenance record as `method="inferred"`.
  4. Abstain throughout: a sample the inference is unsure about stays missing, never guessed.

Generic over any field + inference function; ships a body-site convenience built on `metaqc`. Stdlib only.
"""
from __future__ import annotations
from collections import Counter

try:
    import metaqc
    _CANON = metaqc.canon_site
except Exception:                                 # pragma: no cover
    metaqc = None
    def _CANON(x): return str(x or "").strip().lower()

_ABSTAIN = {"uncertain", "ambiguous", "", None}


def validate_inference(labeled, infer_fn, normalize=_CANON, is_abstain=lambda v: v in _ABSTAIN,
                       min_n: int = 10, min_accuracy: float = 0.7, margin: float = 0.10) -> dict:
    """Measure an inference on held-out deposited labels.

    labeled: iterable of (truth_value, profile). infer_fn(profile) -> (value, raw_confidence).
    Returns a report: n_labeled, n_evaluated (non-abstained), coverage, accuracy, baseline_accuracy
    (majority class), beats_baseline, and `trustworthy` (enough labels, accuracy floor, and beats the
    baseline by `margin`). `applied_confidence` = the measured accuracy iff trustworthy, else None."""
    rows = []
    for truth, prof in labeled:
        val, conf = infer_fn(prof)
        rows.append((normalize(truth), val, is_abstain(val)))
    n_labeled = len(rows)
    evaluated = [(t, normalize(v)) for t, v, ab in rows if not ab]
    n_eval = len(evaluated)
    correct = sum(1 for t, p in evaluated if t == p)
    accuracy = correct / n_eval if n_eval else 0.0
    coverage = n_eval / n_labeled if n_labeled else 0.0
    truths = [t for t, _, _ in rows if t]
    baseline = (max(Counter(truths).values()) / len(truths)) if truths else 0.0
    beats = accuracy > baseline + margin
    trustworthy = (n_labeled >= min_n) and (accuracy >= min_accuracy) and beats
    return {
        "n_labeled": n_labeled, "n_evaluated": n_eval, "coverage": round(coverage, 3),
        "accuracy": round(accuracy, 3), "baseline_accuracy": round(baseline, 3),
        "beats_baseline": beats, "trustworthy": trustworthy,
        "applied_confidence": round(accuracy, 3) if trustworthy else None,
        "note": ("inference beats the naive baseline and clears the floor — apply to unlabeled with "
                 "measured confidence" if trustworthy else
                 "inference does NOT clear the bar (too few labels, low accuracy, or no gain over the "
                 "majority-class baseline) — abstain on all; do not fill this field by inference"),
    }


def apply_inference(unlabeled_profiles, infer_fn, report: dict, normalize=_CANON,
                    is_abstain=lambda v: v in _ABSTAIN) -> list:
    """Apply a VALIDATED inference to unlabeled profiles. Emits an assignment only if the report is
    trustworthy AND the sample doesn't abstain; confidence is the measured accuracy from the report."""
    out = []
    conf = report.get("applied_confidence")
    for prof in unlabeled_profiles:
        if not report.get("trustworthy"):
            out.append({"value": None, "confidence": 0.0, "method": "inferred",
                        "decision": "abstain (inference not validated)"})
            continue
        val, _ = infer_fn(prof)
        if is_abstain(val):
            out.append({"value": None, "confidence": 0.0, "method": "inferred",
                        "decision": "abstain (low per-sample signal)"})
        else:
            out.append({"value": normalize(val), "confidence": conf, "method": "inferred",
                        "source": "taxonomy(self-validated)",
                        "decision": "inferred (measured confidence)"})
    return out


# --------------------------------------------------------------------------- body-site convenience

def _body_site_infer(profile):
    r = metaqc.infer_body_site(profile)
    return r["site"], r["confidence"]


def self_validated_body_site(labeled, unlabeled_profiles, **kw):
    """Validate taxonomy-based body-site inference on `labeled` [(deposited_site, profile)], then apply it
    to `unlabeled_profiles`. Returns (report, assignments). Each assignment can feed
    `provenance.add_inference(pm, 'body_site', a['value'], a['confidence'])`."""
    if metaqc is None:
        raise RuntimeError("metaqc required for body-site inference")
    report = validate_inference(labeled, _body_site_infer, **kw)
    assignments = apply_inference(unlabeled_profiles, _body_site_infer, report)
    return report, assignments
