# Cross-repository metadata indexing

The roadmap item that turns MiDAS from "resolver over a seeded catalog" into a **cross-repository
metadata resolver**: one question reaches across the public microbiome repositories and answers the
field's hardest question — *which datasets actually carry the metadata I need* (disease, host age, diet,
antibiotics, body site, …), normalized so the same field means the same thing across sources.

This is the gap every review names: cMD, MGnify, and Qiita all suffer *missing and inconsistent
metadata*, so cross-study reuse stalls on "does this cohort even record what I need, comparably?".

## Architecture (`crossrepo.py`, stdlib only)

- **Adapters** — one per repository, each emitting the normalized `Dataset` record (the same shape as
  MiDAS's catalog: body sites, assay, tri-state access, n, and a *canonical* metadata-field set).
- **`CANON_METADATA`** — a MIxS-lite controlled vocabulary mapping each repo's heterogeneous field names
  to shared canonical keys (`disease`, `host_age`, `diet`, `antibiotics`, `body_site`, `country`, …).
  `normalize_metadata(raw_keys)` applies it with word-boundary matching (so "age" ≠ "storage",
  "ph" ≠ "morphology").
- **`cross_search(query, need=[...])`** — fans out to the chosen adapters, normalizes, and keeps the
  datasets whose metadata **covers** every requested field; ranks by metadata richness then size.

## Usage

```bash
python crossrepo.py "human gut microbiome"                         # what's there + normalized metadata
python crossrepo.py "human gut microbiome" --need disease,host_age # only datasets carrying BOTH
python crossrepo.py "human gut microbiome" --repos mgnify --json   # machine-readable rows
```

```python
from crossrepo import cross_search
hits = cross_search("human gut microbiome", need=["disease", "diet"], repos=["mgnify"])
```

## Built vs. staged

**Built & live (open REST, no auth):**
- **MGnify** — EBI metagenomics JSON:API; aggregates per-sample structured fields + the free key/value
  `sample-metadata`, infers host (human via host-tax-id 9606) and body sites.
- **NMDC** — National Microbiome Data Collaborative; matches studies by query terms, pulls biosamples via
  `associated_studies`, resolves NMDC's nested ENVO value objects
  (`{"term":{"name":...},"has_raw_value":"ENVO:..."}`) to readable body sites. Environmental-heavy.
- **ENA** — EBI/ENA Portal; human metagenomic `read_run`s grouped to studies (body-site-filtered with a
  fallback, since ENA's `host_body_site` is sparsely populated — itself the honest coverage signal).
  Note: the portal requires `%20` for spaces in `query`, not `+`.
- **dbGaP** — NCBI E-utilities, **discovery-only**: sample/phenotype metadata is *governed*, so the
  adapter finds studies, marks them `controlled` with the application link, and keeps `metadata_fields`
  **empty** — a `--need` query never returns a dbGaP study as if it carried the metadata.

All four validated live and by offline fixtures (`test_crossrepo.py`); one query spans them into one
normalized record set.

**Built, needs a local export (no clean no-auth path):**
- **curatedMetagenomicData** — the richest *harmonized human* metadata, but R-package data.
  `write_cmd_export_R()` emits the one-line R that dumps `sampleMetadata` to TSV; set `MIDAS_CMD_TSV` and
  the adapter groups it by study and reports each populated column. The crown jewel once exported.

**Scaffolded (source not reachable from this build environment):**
- **Qiita** — via `redbiom`; the public redbiom server was unreachable here, so the adapter is a
  documented no-op (returns `[]`) rather than fabricate redbiom's wire format. Much Qiita content is also
  deposited to ENA/EBI (already indexed). To finish: wire the redbiom metadata-category query against a
  reachable `REDBIOM_HOST` and normalize its categories through the same `normalize_metadata`.

## Honest limits

- The vocabulary is a **heuristic MIxS-lite layer**, not a finished ontology — it errs toward precision
  (misses rather than mislabels) and should be reviewed/extended against real field dictionaries.
- MGnify assembly studies often carry sparse metadata (collection date, geo, host) — richer cohort
  metadata lives in the primary study/ENA sample attributes, which deeper hydration can pull.
- Per-study sampling is capped (default 10 samples) to keep queries fast; a field present on only some
  samples is still reported present.
- This complements, not replaces, cMD's deep manual curation — MiDAS points *across* repos and says what
  each carries; it does not re-curate.
