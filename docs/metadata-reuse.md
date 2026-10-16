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
  **← prototyped: `provenance.py`.**
- **C. Resolve-time comparability score.** Flip batch correction from post-hoc to upfront: at discovery,
  output "these N cohorts are ~X% comparable on your needed fields; batch-effect risk Y; correctable via
  ConQuR / MMUPHin." **← prototyped: `comparability.py`.**
- **D. Self-validated inference with abstention.** Address the generalization caution directly: infer a
  field only when calibrated-confident, and **validate each inferred field against the datasets that *did*
  deposit it** (per-repo self-check), reporting measured accuracy — never an opaque guess.
  **← prototyped: `selfvalidate.py`.**

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

## Prototype — comparability score (`comparability.py`, move C)

Given two normalized `Dataset` records, `compare(a, b, need=[...])` returns a **poolability** score (0–1)
with per-dimension subscores, the *limiting factor*, a batch-risk level + recommended correction, and
caveats. Alignment gates (host / body site / assay) dominate — a mismatch there can't be rescued by
metadata — while metadata overlap (of the question's `need` fields) modulates. `rank_comparable(target,
candidates)` orders a resolver's hits by poolability.

**Validated** (`test_comparability.py`): two gut shotgun studies with shared metadata pool at **0.88**
(batch "medium", same uniformly-processed repo); a gut **16S vs shotgun** pair drops to **0.15** (limited
by assay, batch "high" cross-repo); a **gut vs vaginal** pair is **0.00** (blocked by body site, not
rescuable). This is the discovery-time "can I even pool these, and how?" decision, before any download.

## Prototype — provenance / trust records (`provenance.py`, move B)

`ProvenancedMetadata` holds, per canonical field, one `MetaField(value, source, method, confidence)` per
source, over trust tiers **curated > deposited > extracted > inferred**. `best(field)` applies
tier-then-confidence; `fields(min_method, min_confidence)` is the **trust-filtered coverage set** the
resolver / comparability `need` check consumes; `triangulate(field)` reports agree/conflict (carrying
move A as provenance). `from_dataset()` bridges a cross-repo record (cMD → curated, else deposited) and
`add_inference()` attaches a metaqc-style computed value.

**Validated** (`test_provenance.py`): tier ordering (a curated value beats a higher-confidence extracted
one); trust-filtering changes the coverage set; and — the payoff — relaxing the trust floor **moves a
comparability decision** (metadata_overlap 0.67 → 1.00, poolability up) because a shared field exists only
at the extracted tier. This is the layer that ties A, C, and the adapters into one trust-aware record.

## Prototype — self-validated inference (`selfvalidate.py`, move D)

`validate_inference(labeled, infer_fn)` measures an inference on the subset that *did* deposit the field:
accuracy, non-abstention coverage, and whether it **beats the majority-class naive baseline** (the exact
bar the generalization caution sets). `apply_inference(unlabeled, …, report)` fills missing values *only*
if the inference cleared the bar, carrying the **measured accuracy** as confidence — which feeds move-B
provenance as `method="inferred"`. `self_validated_body_site()` wires metaqc's body-site inference in.

**Validated** (`test_selfvalidate.py`): on a 40-sample labeled cohort, body-site inference measures
accuracy 1.0 vs a 0.5 baseline → TRUST, applies to unlabeled with that measured confidence, and abstains
on a no-signal sample; a no-signal *labeled* set correctly fails the bar → abstain on all; and the measured
confidence flows into the provenance record. Nothing is inferred unless it is *measured* to work, and how
well it works **is** the confidence.

## Roadmap — all four moves prototyped
1. ~~Triangulation / mislabel audit (move A)~~ — **built (`metaqc.py`)**; next, extend beyond body site
   (host species, assay type, westernization proxy) — same pattern.
2. ~~Provenance / trust-tiered records (move B)~~ — **built (`provenance.py`)**; next, have the cross-repo
   adapters emit provenanced records natively (not just the flat `metadata_fields` set).
3. ~~Resolve-time comparability score (move C)~~ — **built (`comparability.py`)**; next, fold the
   per-feature batch-risk estimate deeper (platform/pipeline when recorded).
4. ~~Self-validated inference with abstention (move D)~~ — **built (`selfvalidate.py`)**; next, apply it
   across real cross-repo cohorts and publish per-field measured accuracies.

The four moves now form a working, trust-aware cross-repo metadata layer; the next phase is wiring them
through the live resolver end-to-end and measuring on real repo cohorts at scale.

## Honest risks
Inference generalization (hence abstention + self-validation, not black-box prediction); LLM hallucination
on the extraction side (hence provenance + a human review gate — MiDAS already has one); and genus
signatures are a reviewable panel, not a trained model — deliberately, because a mislabel audit must be
legible. This is a research-grade direction (potentially a methods contribution), not a finished product.

Sources: curatedMetagenomicData (Bioconductor); Metalog (NAR 2025); PRIME (PMC12807763); Ikeda et al.
(GigaScience 2025); MicrobeAtlas LLM reclassification (bioRxiv 2025); Metappuccino (bioRxiv 2025);
MicroKPNN-MT (Bioinformatics Advances, vbae203); shotgun body-site classification (ScienceDirect
S0379073821003285); ML-generalization caution (PMC12458437); ConQuR (Nat Commun 2022); MMUPHin.
