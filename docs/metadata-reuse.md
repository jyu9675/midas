# The microbiome metadata-reuse problem — and a trust-first approach

Cross-study microbiome reuse keeps stalling on metadata. This note states the problem precisely, maps
what's already been tried (so MiDAS innovates rather than reinvents), and lays out the approach — with a
working first prototype (`metaqc.py`).

## The problem, decomposed

It is four distinct failures, not one:
1. **Missing** — key fields (diet, disease, drugs, age, timepoint, body-site specifics) were never
   deposited. SRA/ENA submissions are minimal; `"missing"` / `"not collected"` is everywhere.
2. **Inconsistent vocabulary / units** — the same concept under different labels (`sex`/`gender`/`host_sex`;
   `feces`/`stool`/`ENVO:00002003`), and different encodings (age in years vs categories vs infant-days).
3. **Semantically ambiguous** — "healthy control" or "antibiotics" mean different things across studies;
   equal strings are not equal meanings.
4. **Technically non-comparable** — even with matched metadata, platform/pipeline batch effects confound
   pooling.

And a meta-problem underneath all four: **no provenance or trust** — a value is present or absent, with no
record of where it came from or how reliable it is.

## What's already been tried (the honest landscape)

Each obvious lever is an active, crowded area — so none of them, alone, is where to innovate:
- **Manual curation:** curatedMetagenomicData — gold standard, but human-curated and lags the archives.
- **Standards:** MIxS / MIMARKS (GSC), NMDC — voluntary and incompletely filled by submitters.
- **Post-hoc harmonization DBs:** Metalog (~120k samples), PRIME (~53k 16S), GMrepo.
- **LLM extraction / normalization:** Ikeda 2025 (BioSample terms), MicrobeAtlas (GPT-parsed 2M+ SRA
  samples), Metappuccino (SRA reconstruction) — which itself flags LLM **hallucination / value drift**.
- **Inference from the data:** body-site classifiers >99% on shotgun; MicroKPNN-MT predicts missing
  age/BMI/body-site from profiles; KNN host-age imputation. Caveat: a benchmark found such predictors
  often **fail to generalize — worse than a naive mean baseline**.
- **Batch correction:** ConQuR, MMUPHin for cross-study pooling.

## The gap — disconnected and trust-blind

The pieces exist but don't talk to each other, and none carries provenance or produces a *decision*.
Nobody fuses deposited + extracted + inferred metadata into one record that says, per value, *how much to
trust it*, and per dataset pair, *whether they can actually be compared*. That integration/decision layer
is MiDAS's niche. Four moves:

- **A. Triangulation → gap-fill *and error-catching*.** Hold three signals per field — deposited,
  extracted (LLM), inferred (from the data) — and fuse them. Agreement raises confidence; **disagreement
  flags likely-mislabeled or mixed samples** (reframing the work from the crowded "fill missing metadata"
  to the open "audit/correct existing metadata against the data"). **← prototyped: `metaqc.py`.**
- **B. Provenance / trust-tiered records.** Every value = `(value, source, method, confidence)`; the
  resolver filters by trust ("curated disease only" vs "include inferred, conf>0.8"). Honesty as a feature.
- **C. Resolve-time comparability score.** Flip batch correction from post-hoc to upfront: at discovery,
  output "these N cohorts are ~X% comparable on your needed fields; batch-effect risk Y; correctable via
  ConQuR / MMUPHin."
- **D. Self-validated inference with abstention.** Address the generalization caution directly: infer a
  field only when calibrated-confident, and **validate each inferred field against the datasets that *did*
  deposit it** (per-repo self-check), reporting measured accuracy — never an opaque guess.

## Prototype — body-site triangulation (`metaqc.py`, move A)

Body site is the ideal first target: the taxonomic signature predicts it very reliably, so a mismatch is a
trustworthy red flag.
- `infer_body_site(profile)` — a transparent, **specificity-weighted** classifier over genus signatures
  (ubiquitous markers like *Prevotella* are down-weighted; it **abstains** — "ambiguous"/"uncertain" —
  when signal or margin is low, rather than forcing a call).
- `triangulate_body_site(deposited, profile)` — compares deposited vs inferred and returns a verdict
  (`agree` / **`conflict`** / `inferred_only` / `deposited_only` / `uninformative`) with a confidence,
  the method, and the genera that drove it (seeding move B's provenance record).
- `mgnify_genus_profile(study)` — pulls a real genus profile from MGnify to triangulate live.

**Validated:** synthetic vaginal/gut/oral profiles classify correctly and a *Prevotella*-only profile
correctly abstains; the mislabel-catch fires (deposited `vagina` + gut taxonomy → `CONFLICT`); and a live
MGnify study (`MGYS00006849`, deposited "human gut") infers **gut** (Bacteroides / Faecalibacterium /
Blautia / Roseburia, conf 0.85) → `AGREE`. Offline tests in `test_metaqc.py`; `python metaqc.py MGYS…`.

This is a capability none of the existing tools offer: not predicting metadata, but **auditing deposited
metadata against the data** — and it instantiates triangulation + provenance + abstention in one small,
defensible increment.

## Roadmap
1. Extend triangulation beyond body site (host species, assay type, westernization proxy) — same pattern.
2. Attach provenance/trust to every field in the cross-repo record (move B), filterable in the resolver.
3. A resolve-time comparability score (move C), wiring in a batch-effect-risk estimate.
4. Self-validated inference with per-repo accuracy and abstention (move D).

## Honest risks
Inference generalization (hence abstention + self-validation, not black-box prediction); LLM hallucination
on the extraction side (hence provenance + a human review gate — MiDAS already has one); and genus
signatures are a reviewable panel, not a trained model — deliberately, because a mislabel audit must be
legible. This is a research-grade direction (potentially a methods contribution), not a finished product.

Sources: curatedMetagenomicData (Bioconductor); Metalog (NAR 2025); PRIME (PMC12807763); Ikeda et al.
(GigaScience 2025); MicrobeAtlas LLM reclassification (bioRxiv 2025); Metappuccino (bioRxiv 2025);
MicroKPNN-MT (Bioinformatics Advances, vbae203); shotgun body-site classification (ScienceDirect
S0379073821003285); ML-generalization caution (PMC12458437); ConQuR (Nat Commun 2022); MMUPHin.
