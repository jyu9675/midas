#!/usr/bin/env python3
"""Hard-assert the resolve-time comparability score, offline. Run: python test_comparability.py"""
import comparability as C

GUT_SG_A = {"accession": "A", "source_repo": "cmd", "host": "human", "body_sites": ["feces"],
            "assay_types": ["shotgun"], "metadata_fields": {"disease", "host_age", "sex", "diet"}}
GUT_SG_B = {"accession": "B", "source_repo": "cmd", "host": "human", "body_sites": ["feces"],
            "assay_types": ["shotgun"], "metadata_fields": {"disease", "host_age", "sex"}}
GUT_16S = {"accession": "C", "source_repo": "mgnify", "host": "human", "body_sites": ["feces"],
           "assay_types": ["16S"], "metadata_fields": {"disease", "host_age"}}
VAG_SG = {"accession": "D", "source_repo": "ena", "host": "human", "body_sites": ["vagina"],
          "assay_types": ["shotgun"], "metadata_fields": {"disease", "sex"}}

# ---- aligned pair pools high; same uniform repo -> medium batch risk ----
r = C.compare(GUT_SG_A, GUT_SG_B)
assert r["poolability"] >= 0.7 and r["verdict"].startswith("High")
assert r["batch_risk"]["level"] == "medium"
assert r["subscores"]["host_match"] == 1.0 and r["subscores"]["body_site_match"] == 1.0

# ---- need-based metadata overlap: 3 of 4 needed fields in both -> 0.75 ----
r = C.compare(GUT_SG_A, GUT_SG_B, need=["disease", "host_age", "sex", "diet"])
assert abs(r["subscores"]["metadata_overlap"] - 0.75) < 1e-9
assert r["metadata"]["missing_in_b"] == ["diet"]

# ---- assay mismatch (16S vs shotgun) is the limiting factor, and drops the score ----
r = C.compare(GUT_SG_A, GUT_16S)
assert r["limiting_factor"] == "assay_match" and r["poolability"] < 0.4
assert r["batch_risk"]["level"] == "high"            # cross-repo

# ---- different body site cannot be rescued by metadata: blocked, poolability 0 ----
r = C.compare(GUT_SG_A, VAG_SG)
assert r["poolability"] == 0.0 and r["limiting_factor"] == "body_site_match"
assert "Not comparable" in r["verdict"]

# ---- ranking: most-comparable first ----
ranked = C.rank_comparable(GUT_SG_A, [VAG_SG, GUT_16S, GUT_SG_B])
order = [c["accession"] for _, c in ranked]
assert order == ["B", "C", "D"], order

# ---- works on crossrepo.Dataset objects too (not just dicts) ----
try:
    from crossrepo import Dataset
    da = Dataset(source_repo="cmd", accession="A", host="human", body_sites=["feces"],
                 assay_types=["shotgun"], metadata_fields={"disease", "sex"})
    db = Dataset(source_repo="cmd", accession="B", host="human", body_sites=["feces"],
                 assay_types=["shotgun"], metadata_fields={"disease", "sex"})
    assert C.compare(da, db)["poolability"] >= 0.7
except Exception as e:  # pragma: no cover
    raise AssertionError(f"Dataset-object path failed: {e}")

print("ALL COMPARABILITY TESTS PASS  (gut/gut=%.2f, 16S/shotgun=%.2f, gut/vaginal=%.2f)" % (
    C.compare(GUT_SG_A, GUT_SG_B)["poolability"],
    C.compare(GUT_SG_A, GUT_16S)["poolability"],
    C.compare(GUT_SG_A, VAG_SG)["poolability"]))
