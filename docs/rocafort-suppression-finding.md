# A small reanalysis finding: gut taxa tracking HIV viral suppression, filtered by cross-cohort replication

*A hypothesis-generating reanalysis of public data, not a definitive clinical finding.*

## Data
Rocafort et al. 2024, *Nat Commun* (PRJEB41345; DOI 10.1038/s41467-023-44566-4), open-access processed data:
a **597-sample × ~4,500-ASV** 16S table collapsed to **242 genera** (100 after a ≥10% prevalence filter), with
metadata including **HIV phenotype** (277 negative / 224 suppressed / 96 unsuppressed) across **three cohorts**
(Boston, Botswana, Uganda). No raw-read processing — the authors' feature table was used directly.

## Question (a different angle than the paper)
Rocafort 2024 centered **HIV+/− differences and their dependence on host factors** (sexual behavior, geography).
This reanalysis asks a different question on a different axis: **among people with HIV, which gut genera track
viral *suppression* (ART response), and which survive a cross-cohort replication filter?**

## Method
Relative-abundance genus table; **suppressed vs unsuppressed** Mann-Whitney per genus with BH-FDR, run
**separately within each cohort that contains both groups** (Boston, Botswana — Uganda has **0** unsuppressed).
"Replicated" = q < 0.1 in both cohorts, same direction. (Scripted: `scripts/analysis/rocafort_suppression_replication.py`.)

## Result
- A naive **pooled** test flags **52 / 100 genera** — but that is inflated by confounding: unsuppressed subjects
  are **absent from Uganda** and unevenly split between Boston/Botswana, so most of the "signal" is geography.
- Requiring **replication across Boston and Botswana collapses 52 → 2 genera**:

| genus (Greengenes clade) | lineage | direction | suppressed → unsuppressed (mean rel. abund.) |
|---|---|---|---|
| **CF231** | Bacteroidales, *[Paraprevotellaceae]* | higher in unsuppressed | 0.003% → 0.062% (both cohorts +) |
| **02d06** | Clostridiales, *Clostridiaceae* | higher in unsuppressed | 0.011% → 0.062% (both cohorts +) |

Both are also at their **lowest under viral suppression** (below HIV-negative levels), i.e. successful ART
associates with their depletion; loss of viral control associates with their expansion.

## Why it's a (small) finding, and different from the paper
Two things the primary paper did not report: (1) a **cross-cohort replication filter on the suppression axis**,
which shows the ART-response microbiome signal is **overwhelmingly geography-confounded** (52 → 2), a concrete
methodological caution; and (2) **two specific, reproducible candidate taxa** (CF231, 02d06) associated with
uncontrolled HIV across two continents. It reaches the same "host factors dominate" spirit as Rocafort 2024, but
via a replication-first method on a different clinical axis, and it names a robust residual signal.

## Honest limits
Reanalysis of public processed data, not new data. Both taxa are **low-abundance** (~0.01–0.06%) and carry
**Greengenes placeholder names** (CF231, 02d06) — sequence-level follow-up would be needed to resolve and
validate them. The suppression contrast rests on **2 of 3 cohorts** (Uganda lacks unsuppressed subjects).
Genus-level 16S, Mann-Whitney + BH, replication defined as q<0.1 in both cohorts with concordant direction.
This is hypothesis-generating: the value is the **method** (replication-filtered reanalysis) as much as the hits.
