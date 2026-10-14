#!/usr/bin/env python3
"""
Reanalysis: gut genera tracking HIV viral suppression, filtered by cross-cohort replication.
Data: Rocafort et al. 2024, Nat Commun (DOI 10.1038/s41467-023-44566-4; ENA PRJEB41345), open-access
processed 16S feature table + metadata. No raw-read processing.

Finding: a pooled suppressed-vs-unsuppressed test flags ~52/100 genera, but requiring replication across the
two cohorts that contain both groups (Boston, Botswana; Uganda has 0 unsuppressed) collapses this to 2 genera -
CF231 (Paraprevotellaceae) and 02d06 (Clostridiaceae), both higher in unsuppressed (viremic) HIV.

Deps: pandas, numpy, scipy.  Run:  python rocafort_suppression_replication.py
"""
import io, time, urllib.request
import pandas as pd, numpy as np
from scipy.stats import mannwhitneyu

DOI = "10.1038/s41467-023-44566-4"
BASE = "https://static-content.springer.com/esm/art%3A" + DOI.replace(":", "%3A").replace("/", "%2F") + "/MediaObjects/"
FEATURE = "41467_2023_44566_MOESM4_ESM.csv"   # samples x ASVs (semicolon-delimited, BOM)
META    = "41467_2023_44566_MOESM5_ESM.csv"   # samples x clinical variables

def fetch(name, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + name, headers={"User-Agent": "Mozilla/5.0"}), timeout=90) as r:
                return r.read()
        except Exception as e:
            print("  retry %d (%s)" % (i, str(e)[:50])); time.sleep(3)
    raise RuntimeError("could not fetch " + name)

def genus(col):                                # Bacteria_Phylum_Class_Order_Family_Genus_...  -> Genus field
    p = col.split("_"); return p[5] if len(p) > 5 else col

def bh(pvals):
    p = np.array(pvals, float); order = p.argsort()
    q = p * len(p) / np.arange(1, len(p) + 1)
    qs = np.minimum.accumulate(q[order][::-1])[::-1]
    out = np.empty_like(qs); out[order] = qs; return out

def main():
    ft = pd.read_csv(io.BytesIO(fetch(FEATURE)), sep=";", encoding="utf-8-sig")
    md = pd.read_csv(io.BytesIO(fetch(META)),    sep=";", encoding="utf-8-sig")
    # align: feature-table SampleID is the bare id; metadata SampleID is "<id>.<cohort>.<subj>.<date>"
    ft["key"] = ft["SampleID"].astype(str)
    md["key"] = md["SampleID"].astype(str).str.split(".").str[0]
    ft = ft.drop(columns="SampleID").set_index("key")
    md = md.set_index("key")
    g = ft.T.groupby(genus).sum().T                 # collapse ASVs -> genus
    g = g.div(g.sum(axis=1), axis=0)                # relative abundance
    g = g.loc[:, (g > 0).mean() >= 0.10]            # prevalence >= 10%
    df = g.join(md[["HIV_Phenotype", "Cohort"]]).dropna(subset=["HIV_Phenotype"])
    print("aligned samples:", len(df), "| genera:", g.shape[1])
    print(pd.crosstab(df.HIV_Phenotype, df.Cohort))

    sub = df[df.HIV_Phenotype.isin(["2_suppressed", "4_unsuppressed"])]
    def contrast(s):
        rr = []
        for gen in g.columns:
            a = s.loc[s.HIV_Phenotype == "2_suppressed", gen]
            b = s.loc[s.HIV_Phenotype == "4_unsuppressed", gen]
            try: p = mannwhitneyu(a, b).pvalue
            except Exception: p = 1.0
            rr.append((gen, p, np.log2((b.mean() + 1e-6) / (a.mean() + 1e-6))))
        d = pd.DataFrame(rr, columns=["genus", "p", "lfc"]).set_index("genus")
        d["q"] = bh(d.p.values); return d

    pooled = contrast(sub)
    bos = contrast(sub[sub.Cohort == "boston"])
    bot = contrast(sub[sub.Cohort == "botswana"])     # uganda_2 has 0 unsuppressed
    rep = [gen for gen in g.columns
           if bos.loc[gen, "q"] < 0.1 and bot.loc[gen, "q"] < 0.1
           and np.sign(bos.loc[gen, "lfc"]) == np.sign(bot.loc[gen, "lfc"])]
    print("\npooled significant (q<0.1): %d / %d genera" % ((pooled.q < 0.1).sum(), len(pooled)))
    print("replicated across Boston AND Botswana (same direction): %d" % len(rep))
    for gen in rep:
        print("  %-10s  boston log2FC=%+.2f  botswana log2FC=%+.2f  (+ = higher in unsuppressed)"
              % (gen, bos.loc[gen, "lfc"], bot.loc[gen, "lfc"]))

if __name__ == "__main__":
    main()
