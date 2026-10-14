# MiDAS — Microbiome Data & Analysis Search

A question-driven **resolver + analysis-stack recommender** over public microbiome datasets.
Given a real research question, it resolves which datasets are *biologically compatible* and which
executable pipeline answers the question — turning days of literature/data/code hunting into minutes.

**Not** another repository. It sits *on top of* SRA / ENA / dbGaP / Zenodo and encodes the compatibility
judgment a domain expert makes by hand: body-site match → shotgun-vs-16S → **strain-resolution capability**
→ metadata match → pipeline choice → cross-study reuse. The schema is institution-agnostic.

**Live:** https://midas.nuwaslab.com — the resolver over the curated catalog plus live discovery (EuropePMC → ENA).
Beta domain resolvers: `/gut` (gut MGE / resistome) and `/hiv` (HIV/SIV gut, strain-translocation feasibility).

## The key idea
`strain_capable` is a **computed** field, not a scraped one: sequencing depth — the field that decides whether a
dataset can resolve strains — is stated in few papers, so MiDAS computes it from **ENA run-level base counts,
WGS-filtered** (BioProjects routinely bundle 16S + shotgun). Access is **tri-state** (`open` / `controlled` /
`request-only`), not boolean. Body-site / assay need a methods pass + a controlled-vocabulary normalizer.

## Files
- `server.py` — FastAPI app: the UI (`static/`) + the live API (`/api/datasets`, `/api/discover`, `/api/ingest`, `/api/contact`).
- `midas.py` — the stdlib resolver CLI; `hydrate_depth.py` — ENA depth hydration.
- `discover.py` / `ingest.py` / `enrich.py` / `promote.py` — the auto-ingest pipeline (discover → hydrate → enrich → promote).
- `datasets.tsv` / `datasets_hydrated.tsv` — the catalog (rows + ENA-computed depth and data-backed `strain_capable`).
- `schema.yaml` — the record + the two resolver tables (question→data-profile, data-profile→pipeline).
- `static/` — the live site (resolver, FAQ, contact, `/gut`, `/hiv`). `DEPLOY.md` — container + AWS App Runner deploy guide.
- `docs/` — analysis notes (HIV/SIV gut depth audit; a replication-filtered reanalysis). `scripts/` — deploy + analysis helpers.

## Usage
```
python midas.py                 # resolver demo (strain / diet / ecology)
python midas.py "strain sharing and diet"    # free-text -> detected questions
python midas.py --list          # dump catalog
python hydrate_depth.py         # refresh depth-backed strain_capable from ENA -> datasets_hydrated.tsv
python ingest.py PRJNA288562    # auto-ingest stage 3: draft a row from ENA metadata
python discover.py "vaginal rectal microbiome strain" --ingest   # stages 1-2(+3): question -> papers -> accessions -> drafts
python enrich.py PRJNA826539 --write   # stage 4: fill residue into candidates.tsv (review gate; never auto-merged)
uvicorn server:app --port 8080  # the web portal locally
```
The stage-4 LLM refinement is optional (`pip install anthropic` + `ANTHROPIC_API_KEY`); without it, `enrich.py`
runs the deterministic backbone only. The resolver auto-prefers `datasets_hydrated.tsv` (computed `strain_capable`).

## Notes on metadata reality
- Accessions auto-extract at ~80–85% via a multi-repo regex over "Data Availability" sections, but IDs span
  several repositories and newer trials carry 2–4 accessions each (raw + processed + code).
- `depth` is the weakest field and the one `strain_capable` depends on — hence the computed, WGS-filtered approach,
  with retry/pacing (ENA rate-limits batch calls). Depths are *raw* bases; mucosal host-DNA loss is flagged as a
  caveat on `partial` calls.
- Auto-ingest fills ~70% of a row from ENA structured metadata with per-field [auto]/[review] tags; paper-only
  fields (clinical metadata, 16S region, software) route to a human review gate.

## Deploy
`DEPLOY.md` covers the container build and AWS App Runner (ECR image, custom domain, SES contact form). Deploy
config under `scripts/aws/` is templated — replace `<ACCOUNT_ID>` and set `MIDAS_CONTACT_TO` for your own deploy.
