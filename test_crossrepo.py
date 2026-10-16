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


NMDC_STUDIES = {"results": [{"id": "nmdc:sty-test", "name": "Test gut study",
    "title": "Human gut microbiome cohort", "description": "gut microbiome",
    "ecosystem": "Host-associated", "ecosystem_category": "Human",
    "ecosystem_type": "Digestive system"}]}
NMDC_BIOSAMPLES = {"meta": {"count": 42}, "results": [{
    "collection_date": {"has_raw_value": "2020-01-01"},
    "geo_loc_name": {"has_raw_value": "USA"},
    "env_medium": {"term": {"name": "feces"}, "has_raw_value": "ENVO:00002003"},
    "ecosystem": "Host-associated", "ecosystem_category": "Human",
    "ncbi_taxonomy_name": "Homo sapiens"}]}


ENA_RUNS = [
    {"study_accession": "PRJEB0001", "sample_accession": "SAMEA1", "study_title": "Human gut cohort",
     "library_strategy": "WGS", "host_body_site": "feces", "collection_date": "2019",
     "country": "USA", "host_sex": "female", "host_tax_id": "9606"},
    {"study_accession": "PRJEB0001", "sample_accession": "SAMEA2", "study_title": "Human gut cohort",
     "library_strategy": "WGS", "host_body_site": "feces", "collection_date": "2019",
     "country": "USA", "host_sex": "male", "host_tax_id": "9606"},
]
DBGAP_ESEARCH = {"esearchresult": {"idlist": ["111", "222"]}}
DBGAP_ESUMMARY = {"result": {"uids": ["111", "222"],
    "111": {"d_study_name": "Gut microbiome in IBD", "accession": "phs000111"},
    "222": {"title": "Vaginal microbiome and preterm birth", "accession": "phs000222"}}}


def fake_get_json(url, timeout=30):
    if "ena/portal" in url:
        return ENA_RUNS                                    # ENA
    if "eutils.ncbi" in url:
        return DBGAP_ESEARCH if "esearch" in url else DBGAP_ESUMMARY   # dbGaP
    if "microbiomedata.org" in url:
        return NMDC_BIOSAMPLES if "/biosamples" in url else NMDC_STUDIES  # NMDC
    return SAMPLES if "/samples" in url else STUDIES       # MGnify


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

# ---- 3b. NMDC adapter parsing (nested ENVO value objects, biosample->study link) ----
nres = cr.cross_search("gut microbiome", repos=["nmdc"], limit=3)
assert len(nres) == 1, "NMDC study matching the query terms should resolve"
n = nres[0]
assert n.source_repo == "nmdc" and n.host == "human" and n.n_samples == 42
assert {"collection_date", "country", "body_site"}.issubset(n.metadata_fields)
assert "feces" in n.body_sites, "ENVO value object term name should be used, not the ENVO id"

# both repos answer one query -> merged, normalized record set
both = cr.cross_search("gut microbiome", repos=["mgnify", "nmdc"], limit=3)
assert {d.source_repo for d in both} == {"mgnify", "nmdc"}, "cross-repo search spans both sources"

# ---- 3c. ENA adapter (read_run grouped to studies; sparse fields) ----
eres = cr.cross_search("human gut microbiome", repos=["ena"], limit=3)
assert len(eres) == 1
e = eres[0]
assert e.accession == "PRJEB0001" and e.host == "human" and e.n_samples == 2
assert "shotgun" in e.assay_types and "feces" in e.body_sites
assert {"body_site", "collection_date", "country", "sex", "host_species"}.issubset(e.metadata_fields)

# ---- 3d. dbGaP adapter (discovery-only; controlled; metadata governed) ----
gres = cr.cross_search("gut microbiome", repos=["dbgap"], limit=5)
assert len(gres) == 2 and all(d.access == "controlled" for d in gres)
assert all(d.metadata_fields == set() for d in gres), "dbGaP metadata is governed -> not surfaced"
assert gres[0].accession.startswith("phs")
# a --need query must never return a controlled study as if it carried the metadata
assert cr.cross_search("gut microbiome", repos=["dbgap"], need=["disease"]) == []

# ---- 3e. Qiita scaffold returns [] gracefully (redbiom host not wired) ----
assert cr.cross_search("gut microbiome", repos=["qiita"]) == []

# ---- 3f. curatedMetagenomicData reader (local sampleMetadata export) ----
import tempfile, os as _os
cmd_tsv = _os.path.join(tempfile.mkdtemp(), "cmd_sampleMetadata.tsv")
with open(cmd_tsv, "w", encoding="utf-8") as fh:
    fh.write("study_name\tsample_id\tbody_site\tdisease\tage\tgender\tcountry\tantibiotics_current_use\n")
    fh.write("AsnicarF_2021\ts1\tstool\thealthy\t40\tfemale\tITA\tno\n")
    fh.write("AsnicarF_2021\ts2\tstool\tIBD\t51\tmale\tITA\tyes\n")
cmd_hits = cr.CMD(tsv=cmd_tsv).search("stool", limit=3)
assert len(cmd_hits) == 1 and cmd_hits[0].accession == "AsnicarF_2021" and cmd_hits[0].n_samples == 2
assert {"body_site", "disease", "host_age", "sex", "country", "antibiotics"}.issubset(cmd_hits[0].metadata_fields)

r_script = cr.write_cmd_export_R(_os.path.join(tempfile.mkdtemp(), "cmd.R"))
assert "curatedMetagenomicData" in open(r_script).read() and "sampleMetadata" in open(r_script).read()

# ---- 4. serialization to a MiDAS-style row ----
row = d.to_row()
assert row["source_repo"] == "mgnify" and "disease" in row["metadata_fields"].split(";")
assert isinstance(row["metadata_fields"], str)

print("ALL CROSSREPO TESTS PASS  (metadata fields on the stubbed study: %s)"
      % ", ".join(sorted(d.metadata_fields)))
