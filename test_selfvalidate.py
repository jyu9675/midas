#!/usr/bin/env python3
"""Hard-assert self-validated inference with abstention, offline. Run: python test_selfvalidate.py"""
import random
import selfvalidate as SV
import provenance as P

random.seed(7)
def _gut():  return {"Bacteroides": random.randint(300, 600), "Faecalibacterium": random.randint(100, 300),
                     "Blautia": random.randint(50, 150), "Prevotella": random.randint(0, 100)}
def _vag():  return {"Lactobacillus": random.randint(600, 900), "Gardnerella": random.randint(20, 120)}
def _oral(): return {"Streptococcus": random.randint(300, 500), "Veillonella": random.randint(100, 300),
                     "Neisseria": random.randint(50, 200)}

labeled = ([("feces", _gut()) for _ in range(20)]
           + [("vagina", _vag()) for _ in range(10)]
           + [("oral", _oral()) for _ in range(10)])

# ---- 1. validation measures accuracy vs the naive baseline ----
rep = SV.validate_inference(labeled, SV._body_site_infer)
assert rep["n_labeled"] == 40
assert rep["accuracy"] >= 0.9 and rep["beats_baseline"] and rep["trustworthy"]
assert abs(rep["baseline_accuracy"] - 0.5) < 1e-9          # 20/40 gut is the majority class
assert rep["applied_confidence"] == rep["accuracy"]        # confidence = MEASURED accuracy, not hand-set

# ---- 2. apply only to unlabeled; abstain on no-signal samples ----
asg = SV.apply_inference([_gut(), _vag(), {"Escherichia": 500, "Klebsiella": 500}],
                         SV._body_site_infer, rep)
assert asg[0]["value"] == "gut" and asg[0]["confidence"] == rep["accuracy"]
assert asg[1]["value"] == "vaginal"
assert asg[2]["value"] is None and "abstain" in asg[2]["decision"]

# ---- 3. negative control: an inference that can't clear the bar is NOT trusted ----
noise = [("feces", {"Escherichia": random.randint(100, 500)}) for _ in range(15)]
rep_bad = SV.validate_inference(noise, SV._body_site_infer)
assert not rep_bad["trustworthy"] and rep_bad["applied_confidence"] is None
bad_apply = SV.apply_inference([_gut()], SV._body_site_infer, rep_bad)
assert bad_apply[0]["value"] is None and "not validated" in bad_apply[0]["decision"]

# ---- 4. D -> B handoff: the MEASURED confidence flows into the provenance record ----
rep2, asg2 = SV.self_validated_body_site(labeled, [_gut()])
pm = P.ProvenancedMetadata()
P.add_inference(pm, "body_site", asg2[0]["value"], asg2[0]["confidence"])
mf = pm.best("body_site")
assert mf.method == "inferred" and mf.confidence == rep2["applied_confidence"]

print("ALL SELFVALIDATE TESTS PASS  (accuracy=%.2f vs baseline=%.2f -> %s; confidence is measured)"
      % (rep["accuracy"], rep["baseline_accuracy"], "TRUST" if rep["trustworthy"] else "ABSTAIN"))
