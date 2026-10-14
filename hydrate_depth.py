#!/usr/bin/env python3
"""
MiDAS depth-hydration: query ENA for run-level base counts and turn the asserted
`strain_capable` flags (compute/partial) into DATA-BACKED calls.

For each dataset with a shotgun accession, pull per-sample bases from the ENA Portal API,
take the median Gbp/sample, and classify strain-resolution capability. 16S -> no;
isolate-WGS/long-read -> yes (strain-resolved by design, no API needed).

Writes datasets_hydrated.tsv (adds depth_gbp_median, strain_capable_hydrated, depth_source).
Stdlib only.

Usage:
  python hydrate_depth.py                 # hydrate the whole catalog
  python hydrate_depth.py --test PRJNA288562   # probe one accession
"""
import csv, os, sys, re, json, time, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
TSV = os.path.join(HERE, "datasets.tsv")
OUT = os.path.join(HERE, "datasets_hydrated.tsv")
ENA = "https://www.ebi.ac.uk/ena/portal/api/filereport"

# raw bases/sample thresholds (raw, pre-host-removal; vaginal loses a lot to host -> caveat noted)
YES_GBP, PARTIAL_GBP = 3.0, 1.0

def ena_bases(accession, only="WGS", timeout=90):
    """Median Gbp/sample over runs whose library_strategy==`only` (shotgun=WGS).
    Returns (median_gbp, n_samples_in_subset, note). Filtering out AMPLICON is essential:
    many BioProjects bundle 16S + shotgun, and an unfiltered median is 16S-dominated."""
    q = urllib.parse.urlencode({
        "accession": accession, "result": "read_run",
        "fields": "sample_accession,base_count,read_count,library_strategy", "format": "tsv"})
    txt = None
    for attempt in range(3):                     # retry: ENA rate-limits rapid batch calls
        try:
            with urllib.request.urlopen(ENA + "?" + q, timeout=timeout) as r:
                txt = r.read().decode("utf-8", "replace")
            break
        except Exception as e:
            last = type(e).__name__
            time.sleep(2 * (attempt + 1))
    if txt is None:
        return None, 0, "ERR:%s" % last
    lines = [l for l in txt.splitlines() if l.strip()]
    if len(lines) < 2:
        return None, 0, "no-runs"
    hdr = lines[0].split("\t"); ix = {c: i for i, c in enumerate(hdr)}
    per_sample, strat_counts = {}, {}
    for ln in lines[1:]:
        f = ln.split("\t")
        strat = f[ix["library_strategy"]] if ix.get("library_strategy", 99) < len(f) else ""
        strat_counts[strat] = strat_counts.get(strat, 0) + 1
        if only and strat.upper() != only.upper():
            continue
        try:
            bc = int(f[ix["base_count"]]) if f[ix["base_count"]] else 0
        except Exception:
            bc = 0
        samp = f[ix["sample_accession"]] if ix.get("sample_accession", 99) < len(f) else f[0]
        per_sample[samp] = per_sample.get(samp, 0) + bc
    mix = ",".join("%s:%d" % (k or "?", v) for k, v in sorted(strat_counts.items()))
    vals = sorted(v for v in per_sample.values() if v > 0)
    if not vals:
        return None, 0, "no %s runs (mix: %s)" % (only, mix)
    med = vals[len(vals)//2] / 1e9
    return med, len(vals), "%s runs; mix: %s" % (only, mix)

def classify(assay_types, med_gbp):
    a = assay_types.lower()
    if re.search(r"isolate|genome|long-read", a):      # isolate-WGS, isolate-genomes, long-read genomes
        return "yes", "isolate/genome/long-read = strain-resolved by design"
    if "shotgun" not in a:
        return "no", "16S/amplicon only - no strain resolution"
    if med_gbp is None:
        return "compute", "shotgun but ENA depth unavailable"
    if med_gbp >= YES_GBP:
        return "yes", "%.2f Gbp/sample (>=%.0f)" % (med_gbp, YES_GBP)
    if med_gbp >= PARTIAL_GBP:
        return "partial", "%.2f Gbp/sample (host loss may limit target coverage)" % med_gbp
    return "partial", "%.2f Gbp/sample - shallow; likely <10x on target species" % med_gbp

def first_prj(accessions):
    m = re.search(r"PRJ[EN][AB]\d+", accessions)
    return m.group(0) if m else None

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        acc = sys.argv[2]
        med, n, strat = ena_bases(acc)
        print("%s -> median %.3f Gbp/sample across %d samples (ENA strategy=%s)" %
              (acc, med or 0, n, strat))
        return
    rows = list(csv.DictReader(open(TSV, newline="", encoding="utf-8"), delimiter="\t"))
    fields = list(rows[0].keys()) + ["depth_gbp_median", "strain_capable_hydrated", "depth_source"]
    changed = 0
    for r in rows:
        assay = r["assay_types"]
        prj = first_prj(r["accessions"])
        med, n, strat = (None, 0, "")
        # only hit ENA for shotgun datasets that aren't already strain-resolved-by-design
        pre = classify(assay, None)[0]
        if pre != "yes" and "shotgun" in assay.lower() and prj and r["access"].lower() != "none" and "request-only" not in r["access"].lower():
            med, n, strat = ena_bases(prj)
            time.sleep(1)                               # pace calls to avoid ENA rate-limit
        new, why = classify(assay, med)
        r["depth_gbp_median"] = ("%.2f" % med) if med is not None else ""
        r["strain_capable_hydrated"] = new
        r["depth_source"] = (("ENA %s (%d samp)" % (prj, n)) if med is not None else why)
        old = re.sub(r"\(.*?\)", "", r["strain_capable"]).strip().lower()
        flag = " *CHANGED* %s->%s" % (old, new) if new != old else ""
        if flag: changed += 1
        print("%-4s %-30s shotgun=%s depth=%s -> %s%s" %
              (r["id"], r["citation"][:30], "shotgun" in assay.lower(),
               r["depth_gbp_median"] or "n/a", new, flag))
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader(); w.writerows(rows)
    print("\nwrote %s  (%d strain_capable calls changed by real depth)" % (OUT, changed))

if __name__ == "__main__":
    main()
