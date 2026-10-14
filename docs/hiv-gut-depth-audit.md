# Depth audit of the public HIV/SIV gut microbiome corpus

*A small, reproducible meta-result from MiDAS: the empirical backbone of the "sequence deeper for strain work" argument.*

## Question
Microbial translocation and dysbiosis in HIV/SIV are usually studied at the **composition** level. Resolving
*which strains* translocate needs **deep shotgun** sequencing. So: how much of the **public** HIV/SIV gut
microbiome corpus is actually deep enough to attempt strain-level work?

## Method
Assembled public HIV/SIV gut datasets by literature discovery (EuropePMC), kept those confirmed HIV/SIV from the
study title/citation, and for each computed sequencing depth from **ENA run-level base counts** (WGS-filtered),
then classified strain-feasibility (`yes` ≈ ≥3 Gbp/sample shotgun, `partial` = shallower shotgun, `no` = 16S or
compute-only). Table: `hiv_gut_depth_audit.tsv`.

## Result (N = 12 datasets)
| class | datasets | share |
|---|---|---|
| **Strain-feasible** (deep shotgun, ≥~3 Gbp) | 3 | **25%** |
| Partial (shallow shotgun) | 3 | 25% |
| Not feasible (16S) | 6 | **50%** |

- **Half the corpus is 16S** — it can name taxa but cannot resolve strains at all.
- **Only a quarter is deep enough** for confident strain-level analysis (PRJNA692830 12.5 Gbp, PRJNA1263627
  10.9 Gbp, PRJEB76817 6.7 Gbp — all human HIV).
- **Every SIV dataset in the set is 16S** (Flynn 2024 translocating-bacteria; Brochu 2024 vaccine; Premadasa
  2026 SIV/THC). So **strain-resolved translocation has essentially never been done on public SIV data**, even
  though the SIV model is where translocation mechanism is studied.

## Why it's a (small) finding, and different from what's published
It is not a new microbial result — it is a **feasibility audit of the field's data**, which the primary papers
don't report. It quantifies a gap: the mechanistic question (which strains cross the gut barrier) is
**under-powered in public data**, and the SIV model — the mechanistic workhorse — is entirely amplicon-level.
That is a concrete, defensible argument for **deeper paired (lumen + tissue/plasma) shotgun sequencing**, which
is exactly the contribution a strain-level analyst would bring.

## Honest limits
N = 12 is a **discovery-limited sample** of the public corpus, not an exhaustive census; controlled-access
cohorts (dbGaP) are not included and some are deeper. The depth threshold is a rule of thumb; true per-species
strain coverage depends on the target's abundance and host-DNA fraction. Still, the direction is robust: the
open HIV/SIV gut corpus skews shallow/amplicon for strain purposes.

## Next step toward an actual microbial finding
Because deep HIV/SIV *shotgun* is scarce (this audit; and MGnify's HIV studies are mostly lung, cMD is
shotgun-only), a cross-cohort shotgun meta-analysis is thin. The feasible biological result is a **single
well-chosen 16S dataset reanalyzed with a different method** — e.g. Flynn 2024 SIV translocation (PRJNA1032631,
216 samples, 16S): the paper argued translocation is "not stochastic"; an ML feature-importance or
co-occurrence-network angle (light, laptop-feasible) asks *which* taxa drive it, complementary to their stats.
