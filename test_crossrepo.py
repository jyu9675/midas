#!/usr/bin/env python3
"""Hard-assert the cross-repo metadata layer, offline. Run: python test_crossrepo.py

Network is stubbed with a faithful MGnify JSON:API fixture (the shape confirmed against the live API),
so this is deterministic and runs anywhere."""
import crossrepo as cr

# ---- 1. canonical metadata vocabulary (pure, no network) ----
assert cr.normalize_metadata(["host age"]) == {"host_age"}, \
    "bare 'host' must NOT trigger host_species on 'host age'"
assert cr.normalize_metadata(["host-tax-id"]) == {"host_species"}
assert cr.normalize_metadata(["disease status"]) == {"disease"}
assert cr.normalize_metadata(["geo-loc-name"]) == {"country"}
assert cr.normalize_metadata(["environment-material"]) == {"body_site"}
assert "diet" in cr.normalize_metadata(["Dietary intake (FFQ)"])
assert cr.normalize_metadata(["storage temperature"]) == set(), "'age' in 'storage' must not match"
assert cr.normalize_metadata(["morphology"]) == set(), "'ph' in 'morphology' must not match"

# coverage logic
assert cr.coverage({"disease", "diet", "host_age"}, ["disease", "diet"])
assert not cr.coverage({"disease"}, ["disease", "diet"])

# ---- 2. MGnify adapter parsing, with the network stubbed ----
STUDIES = {"data": [{"id": "MGYS00000001", "attributes": {
    "accession": "MGYS00000001", "study-name": "Test human gut cohort",
    "samples-count": 12, "bioproject": "PRJNA000001"}}]}
SAMPLES = {"data": [
    {"attributes": {"host-tax-id": "9606", "species": "human gut metagenome",
                    "environment-material": "stool", "collection-date": "2019-05-01",
                    "geo-loc-name": "United Kingdom",
                    "sample-metadata": [{"key": "sex", "value": "female"},
                                        {"key": "host age", "value": "42"},
                                        {"key": "disease", "value": "Crohn's disease"},
                                        {"key": "antibiotics", "value": "no"}]}},
    {"attributes": {"host-tax-id": "9606", "species": "human gut metagenome",
                    "environment-material": "stool",
                    "sample-metadata": [{"key": "diet", "value": "omnivore"}]}},
]}


def fake_get_json(url, timeout=30):
    return SAMPLES if "/samples" in url else STUDIES


cr.get_json = fake_get_json                 # stub the only network call

res = cr.cross_search("human gut microbiome", repos=["mgnify"], limit=3)
assert len(res) == 1
d = res[0]
assert d.source_repo == "mgnify" and d.accession == "MGYS00000001"
assert d.host == "human" and d.n_samples == 12 and d.access == "open"
for f in ("disease", "diet", "host_age", "antibiotics", "body_site", "country", "sex", "host_species"):
    assert f in d.metadata_fields, f"expected {f} in normalized metadata, got {sorted(d.metadata_fields)}"
assert "stool" in d.body_sites

# ---- 3. the metadata-coverage filter (the headline feature) ----
assert len(cr.cross_search("gut", repos=["mgnify"], need=["disease", "diet"])) == 1, \
    "dataset carries BOTH disease and diet -> kept"
assert len(cr.cross_search("gut", repos=["mgnify"], need=["bmi"])) == 0, \
    "dataset has no BMI -> filtered out"

# ---- 4. serialization to a MiDAS-style row ----
row = d.to_row()
assert row["source_repo"] == "mgnify" and "disease" in row["metadata_fields"].split(";")
assert isinstance(row["metadata_fields"], str)

print("ALL CROSSREPO TESTS PASS  (metadata fields on the stubbed study: %s)"
      % ", ".join(sorted(d.metadata_fields)))
