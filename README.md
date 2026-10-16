# MiDAS — Microbiome Data & Analysis Search

A question-driven **metadata resolver for microbiome/gut datasets**. You ask a real research question —
*"gut shotgun cohorts that also have dietary intake and disease status", "paired gut+vaginal with
strain-capable depth", "longitudinal infant gut with antibiotic exposure"* — and MiDAS resolves **which
public datasets actually carry the metadata you need**, whether the data is *capable* of answering it
(depth, 16S vs shotgun, paired sites, longitudinal), and the executable pipeline that fits — turning days
of literature/data/code hunting into minutes.

**Not** another repository. It sits *on top of* the public stores (SRA / ENA / dbGaP / Zenodo today;
curatedMetagenomicData / MGnify / Qiita / NMDC on the roadmap) and encodes the compatibility judgment a
domain expert makes by hand: body-site → shotgun-vs-16S → **strain-resolution capability** → **metadata
coverage & comparability** → pipeline choice → cross-study reuse. The schema is institution- and
repository-agnostic.

**Domain analyses plug in on top** of the resolver, which finds the data: **vmbdiet** (diet↔vaginal
microbiome), **strainshare** (strain-sharing), **engrafttracker** (HSCT engraftment).

**Live:** https://midas.nuwaslab.com — the resolver over the curated catalog plus live discovery (EuropePMC → ENA).
Beta domain resolvers: `/gut` (gut MGE / resistome) and `/hiv` (HIV/SIV gut, strain-translocation feasibility).

## The key idea
`strain_capable` is a **computed** field, not a scraped one: sequencing depth — the field that decides whether a
dataset can resolve strains — is stated in few papers, so MiDAS computes it from **ENA run-level base counts,
WGS-filtered** (BioProjects routinely bundle 16S + shotgun). Access is **tri-state** (`open` / `controlled` /
`request-only`), not boolean. Body-site / assay need a methods pass + a controlled-vocabulary normalizer.

## What it resolves today vs. the roadmap

Stated plainly so the live catalog isn't mistaken for the full vision:

**Today (built & live):**
- Resolves a curated + auto-discovered catalog; live discovery runs EuropePMC → ENA.
- **Computes** dataset capability rather than scraping it: `strain_capable` from ENA run-level depth
  (WGS-filtered), body-site/assay from a methods pass, **tri-state** access.
- Per-record metadata fields + a pipeline recommendation; beta domain resolvers `/gut`, `/hiv`.
- Auto-ingest pipeline (discover → hydrate → enrich → promote) with a human review gate.

**Roadmap (the metadata-resolver vision — partly started; don't infer the rest from the live catalog):**
- **Cross-repository indexing** — built (`crossrepo.py`): live **MGnify + NMDC + ENA** adapters +
  **dbGaP** discovery (controlled) + a canonical metadata vocabulary + a "which datasets carry fields
  X, Y, Z" coverage query, spanning sources from one query. **curatedMetagenomicData** via
  `scripts/cmd_from_curation.py` (no R) or a one-line R export, set `MIDAS_CMD_TSV` (validated on a real
  5-study / 1,664-sample pull); **Qiita**/redbiom scaffolded (server unreachable here). See
  [docs/crossrepo.md](docs/crossrepo.md).
- **Metadata-coverage resolver** — answer "which datasets carry fields X, Y, Z" (phenotype / clinical /
  diet / host / exposure) and flag how comparable those fields are across studies, since missing and
  inconsistent metadata is the field's main blocker to cross-study reuse.
- **Controlled-vocabulary normalization** — align heterogeneous metadata to MIxS / MIMARKS so "diet",
  "antibiotics", and "disease status" mean the same thing across cohorts.
- **Metadata QC / trust layer** — *all 4 moves prototyped*: cross-check deposited metadata against the
  data itself (`metaqc.py` — body-site triangulation flags likely-mislabeled samples), trust-tiered
  provenance records (`provenance.py`), resolve-time dataset-pair poolability (`comparability.py`), and
  self-validated inference with abstention (`selfvalidate.py`). Next: wire them through the live resolver
  and measure on real cohorts at scale. See [docs/metadata-reuse.md](docs/metadata-reuse.md).

## Files
- `server.py` — FastAPI app: the UI (`static/`) + the live API (`/api/datasets`, `/api/discover`, `/api/ingest`, `/api/contact`).
- `midas.py` — the stdlib resolver CLI; `hydrate_depth.py` — ENA depth hydration.
- `crossrepo.py` — cross-repository metadata search: MGnify/NMDC/ENA/dbGaP adapters (+ curatedMetagenomicData export-reader, Qiita/redbiom scaffold) + canonical vocab + coverage query; `docs/crossrepo.md`.
- `metaqc.py` — metadata QC by triangulation: cross-checks a deposited body site against the taxonomy-inferred one (specificity-weighted, abstains when unsure) to flag **likely-mislabeled** samples; `docs/metadata-reuse.md`.
- `comparability.py` — resolve-time **poolability** score for a pair of datasets (host/body-site/assay gates + metadata overlap + batch-effect risk → "can these be pooled, and how?") before any download; `docs/metadata-reuse.md`.
- `provenance.py` — **trust-tiered** metadata records: every value carries `(source, method, confidence)` over curated > deposited > extracted > inferred; trust-filtered coverage + agree/conflict triangulation (ties the QC + comparability layers together); `docs/metadata-reuse.md`.
- `selfvalidate.py` — **self-validated** inference: fills a missing field only when the inference is *measured* to beat a naive baseline on datasets that did deposit it, reporting that measured accuracy as the confidence (abstains otherwise); `docs/metadata-reuse.md`.
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
python crossrepo.py "human gut microbiome" --need disease,host_age   # cross-repo: which datasets carry these metadata (live MGnify)
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
