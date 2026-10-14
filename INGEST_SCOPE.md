# MiDAS auto-ingest — prototype scope

**Goal.** Turn the curated 37-row seed into a *living* catalog: given an accession (later: a query or a lab), auto-draft a MiDAS row from public-repository APIs, computing the load-bearing fields, and route only the genuine residue to a human-review queue.

## Pipeline (4 stages, different automation confidence)
1. **Discover** candidates — EuropePMC literature search (`discover.py`), query scoped to primary data-depositing microbiome papers. **BUILT.**
2. **Extract accessions** — regex (`PRJ[EN][AB]\d+ | E-MTAB-\d+ | GSE\d+ | phs\d+ | [SED]RP\d+`) over each paper's EuropePMC open-access **full-text XML** (fallback: abstract). **BUILT** (`discover.py`).
3. **Hydrate from repository APIs** — the high-confidence core (`ingest.py`). ENA `filereport` (read_run): `library_strategy`, `scientific_name`, `sample_title`, `collection_date`, `base_count`, `host`, `fastq_ftp` → most of the row. **BUILT.**
4. **Curate the residue** — clinical metadata, 16S region, software/code, citation, cohort, subject count. **BUILT** (`enrich.py`): deterministic backbone (software dictionary, code-URL/16S-region regex, citation from EuropePMC, clinical-keyword scan — stdlib) + OPTIONAL LLM refinement (official `anthropic` SDK, model claude-opus-5, for cohort/exact-n/metadata-filtering) that degrades gracefully to deterministic-only when no SDK/key. Writes filled fields back into `candidates.tsv`.

**All four stages built.** End-to-end validated: `discover.py "..." --ingest` then `enrich.py <acc> --write` assembles a near-complete catalog row (e.g. Bommana PRJNA826539: sites/paired/shotgun/depth/access/n/citation/software/code/metadata) with only cohort + exact n_subjects flagged for the LLM/human. Deterministic clinical-keyword scan is intentionally over-inclusive -> the LLM pass filters it.

**Full chain built:** `discover.py "<query>" --ingest` = stages 1→2→3 (question → papers → accessions → hydrated draft rows in `candidates.tsv`). Validated: a query re-discovers hand-curated rows (Krog PRJEB37731, Sterpu PRJEB38528, Bommana PRJNA826539) and reproduces their depth calls, plus surfaces new candidates.

## Confidence map (what each field comes from)
| Field | Source | Confidence |
|---|---|---|
| assay_types (shotgun / 16S) | ENA `library_strategy` (WGS / AMPLICON) | **auto — high** |
| host | ENA `scientific_name` / `host` | **auto — high** |
| body_sites | ENA `scientific_name` ("…vaginal metagenome") + `sample_title` keywords → vocab normalizer | **auto — medium-high** |
| paired_sites | ≥2 distinct body sites in the project | **auto — high** |
| longitudinal | `collection_date` spread + timepoint words ("day/week/visit") in `sample_title` | **auto — medium** |
| depth → strain_capable | ENA `base_count`, **WGS-filtered**, median Gbp/sample (`hydrate_depth.py`) | **auto — high** |
| n_samples | distinct `sample_accession` | **auto — high** |
| access | public `fastq_ftp` → open; `phs` → controlled; registered but no runs → embargoed | **auto — high** |
| n_subjects | parse "Subject X" from `sample_title` (when present) | auto — low (flag) |
| key_metadata (BV, diet, pH…) | paper methods / ENA sample attributes (rarely) | **review — paper** |
| 16S region (V4…) | paper methods | **review — paper** |
| software / code | paper Code-Availability regex | **review — paper** |

## Prototype IN / OUT
- **IN:** `ingest.py <accession>` → ENA hydration → draft row with the 8 auto fields above, a controlled-vocabulary **body-site normalizer**, per-field **confidence tags**, and a **review queue** listing the paper-only fields. Appends to `candidates.tsv` (never auto-merges into the curated catalog — review gate).
- **OUT (next phases):** paper fetch + accession regex (stage 2); PubMed/ENA discovery search (stage 1); LLM extraction of clinical metadata/16S/software (stage 4); dbGaP-controlled hydration; de-dup against existing rows.

## Acceptance test
Auto-ingest **PRJNA288562** (Goltsman) with zero hand input and reproduce the key fields of the hand-curated row `d28`: body_sites = vagina+gut+oral, paired_sites = yes, assay = shotgun(+amplicon), depth ≈ 0.35 Gbp → strain_capable = partial, access = open. If auto == hand on those, the structured-hydration thesis holds.

## Risks / honest limits
- Some BioProjects have bare `sample_title` (no site/subject) → body_site falls to review. The normalizer must fail *to review*, never guess.
- SRA-only accessions not mirrored to ENA → fall back to NCBI eutils (phase 2).
- Subject count is genuinely hard from metadata alone — low-confidence, flagged.
- Mixed 16S+shotgun projects handled by the WGS filter (already proven).
- Rate limits → retry/pacing (already in `hydrate_depth.py`).
