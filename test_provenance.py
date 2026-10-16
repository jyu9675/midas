#!/usr/bin/env python3
"""Hard-assert the provenance / trust-tiered records, offline. Run: python test_provenance.py"""
import provenance as P
import comparability as C

# ---- 1. tier-then-confidence ordering in best() ----
pm = P.ProvenancedMetadata()
pm.add("disease", "IBD", source="paper", method="extracted", confidence=0.99)
pm.add("disease", "IBD", source="cmd", method="curated", confidence=0.70)
# curated tier beats extracted even though extracted had higher confidence
assert pm.best("disease").method == "curated"
pm.add("host_age", "40", source="ena", method="deposited", confidence=0.5)
pm.add("host_age", "41", source="ena2", method="deposited", confidence=0.9)
# within a tier, higher confidence wins
assert pm.best("host_age").confidence == 0.9

# ---- 2. trust-filtered coverage (fields) ----
pm2 = P.ProvenancedMetadata()
pm2.add("disease", source="cmd", method="curated")
pm2.add("diet", source="paper", method="extracted", confidence=0.6)
pm2.add("body_site", "feces", source="taxonomy", method="inferred", confidence=0.85)
assert pm2.fields(min_method="curated") == {"disease"}
assert pm2.fields(min_method="extracted") == {"disease", "diet"}
assert pm2.fields(min_method="inferred") == {"disease", "diet", "body_site"}
# a confidence floor drops the low-confidence extracted field
assert "diet" not in pm2.fields(min_method="inferred", min_confidence=0.8)

# ---- 3. triangulation: agree / conflict / single ----
tri = P.ProvenancedMetadata()
tri.add("body_site", "feces", source="ena", method="deposited")
tri.add("body_site", "stool", source="cmd", method="curated")   # canon(feces)==canon(stool)==gut
assert tri.triangulate("body_site")["status"] == "agree"
tri.add("body_site", "vagina", source="taxonomy", method="inferred", confidence=0.9)
assert tri.triangulate("body_site")["status"] == "conflict"     # gut vs vaginal
assert P.ProvenancedMetadata().add("disease", "x", method="deposited").triangulate("disease")["status"] == "single"

# ---- 4. from_dataset assigns the right tier by repo ----
assert P.from_dataset({"source_repo": "cmd", "metadata_fields": {"disease"}}).best("disease").method == "curated"
assert P.from_dataset({"source_repo": "mgnify", "metadata_fields": {"disease"}}).best("disease").method == "deposited"

# ---- 5. the payoff: trust level changes a comparability decision ----
# both datasets carry 'diet' only at EXTRACTED tier; disease/host_age are deposited.
def ds(acc, fields):
    return {"accession": acc, "source_repo": "mgnify", "host": "human",
            "body_sites": ["feces"], "assay_types": ["shotgun"], "metadata_fields": fields}

pa = P.ProvenancedMetadata(); pb = P.ProvenancedMetadata()
for pm_ in (pa, pb):
    pm_.add("disease", method="deposited"); pm_.add("host_age", method="deposited")
    pm_.add("diet", source="paper", method="extracted", confidence=0.6)

need = ["disease", "host_age", "diet"]
# curated/deposited-only view: 'diet' absent -> only 2/3 needed fields shared
dep = C.compare(ds("A", pa.fields(min_method="deposited")), ds("B", pb.fields(min_method="deposited")), need=need)
# include extracted: 'diet' now present in both -> full overlap
ext = C.compare(ds("A", pa.fields(min_method="extracted")), ds("B", pb.fields(min_method="extracted")), need=need)
assert dep["subscores"]["metadata_overlap"] < ext["subscores"]["metadata_overlap"]
assert ext["subscores"]["metadata_overlap"] == 1.0
assert ext["poolability"] > dep["poolability"]

print("ALL PROVENANCE TESTS PASS  (trust filter moved metadata_overlap %.2f -> %.2f)"
      % (dep["subscores"]["metadata_overlap"], ext["subscores"]["metadata_overlap"]))
