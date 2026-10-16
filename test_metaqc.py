#!/usr/bin/env python3
"""Hard-assert the metadata-QC triangulation, offline (pure functions). Run: python test_metaqc.py"""
import metaqc as m

# ---- 1. body-site inference from a genus profile ----
vaginal = {"Lactobacillus": 900, "Gardnerella": 60, "Prevotella": 40}
gut     = {"Bacteroides": 500, "Faecalibacterium": 300, "Prevotella": 100, "Blautia": 100}
oral    = {"Streptococcus": 400, "Veillonella": 300, "Neisseria": 200, "Prevotella": 100}

assert m.infer_body_site(vaginal)["site"] == "vaginal"
assert m.infer_body_site(gut)["site"] == "gut"
assert m.infer_body_site(oral)["site"] == "oral"
assert m.infer_body_site(vaginal)["confidence"] > 0.8

# specificity weighting: a profile dominated by a MULTI-site genus must NOT force a confident call
assert m.infer_body_site({"Prevotella": 900, "Escherichia": 100})["site"] in ("ambiguous", "uncertain")
# too little signature signal -> abstain
assert m.infer_body_site({"Escherichia": 500, "Klebsiella": 500})["site"] == "uncertain"
assert m.infer_body_site({})["site"] == "uncertain"

# ---- 2. canonical body-site mapping ----
assert m.canon_site("feces") == "gut" and m.canon_site("posterior fornix") == "vaginal"
assert m.canon_site("saliva") == "oral" and m.canon_site("not collected") == ""

# ---- 3. triangulation verdicts ----
assert m.triangulate_body_site("feces", gut)["verdict"] == "agree"
# the headline capability: deposited label disagrees with the taxonomy -> flag likely mislabel
conflict = m.triangulate_body_site("vagina", gut)
assert conflict["verdict"] == "conflict" and "mislabel" in conflict["note"]
assert conflict["inferred_site"] == "gut" and conflict["deposited_canon"] == "vaginal"
# deposited missing -> inferred fills the gap (flagged)
assert m.triangulate_body_site("", vaginal)["verdict"] == "inferred_only"
# taxonomy inconclusive -> keep deposited, uncorroborated
assert m.triangulate_body_site("stool", {"Prevotella": 900})["verdict"] == "deposited_only"
# neither -> uninformative
assert m.triangulate_body_site("", {"Prevotella": 900})["verdict"] == "uninformative"

# ---- 4. verdict carries provenance (method + confidence + evidence) ----
v = m.triangulate_body_site("feces", gut)
assert v["method"].startswith("taxonomy-signature") and v["evidence"] and 0 <= v["inferred_confidence"] <= 1

print("ALL METAQC TESTS PASS  (mislabel-catch: deposited=vagina + gut-taxonomy -> %s)"
      % m.triangulate_body_site("vagina", gut)["verdict"].upper())
