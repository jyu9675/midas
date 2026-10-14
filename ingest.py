#!/usr/bin/env python3
"""
MiDAS auto-ingest prototype (stage 3: repository hydration).

Given an ENA/SRA BioProject accession, auto-draft a MiDAS row from ENA's STRUCTURED
sample metadata + run-level depth — no paper needed. Fills the high-confidence fields,
normalizes body sites to a controlled vocabulary, tags each field [auto]/[review], and
routes the paper-only residue (clinical metadata, 16S region, software) to a review list.
Appends to candidates.tsv (NEVER auto-merges into the curated catalog — review gate).

Usage:
  python ingest.py PRJNA288562
  python ingest.py PRJEB50325 --append      # also write a row to candidates.tsv
Stdlib only.
"""
import sys, os, re, time, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ENA = "https://www.ebi.ac.uk/ena/portal/api/filereport"
FIELDS = ("run_accession,sample_accession,library_strategy,library_source,scientific_name,"
          "sample_title,collection_date,base_count,fastq_ftp,host")
YES_GBP, PARTIAL_GBP = 3.0, 1.0

# controlled vocabulary: text pattern -> canonical body site (fail to review, never guess)
VOCAB = [(r"vagin|posterior fornix", "vagina"), (r"cervi", "cervix"),
         (r"rect", "rectum"), (r"stool|feces|faec|distal gut|gut metagenome|\bgut\b|intestin", "gut"),
         (r"oral|saliva|buccal|tongue|tooth|plaque|mouth|supraging", "oral"),
         (r"skin|pore|forehead|cheek|antecubital|sebum", "skin"),
         (r"nasal|nares|nasophary|nostril", "nasal"), (r"semen|penile|coronal sulcus", "penile")]
TIMEWORDS = re.compile(r"\b(day|week|wk|month|visit|timepoint|time point|gestational|trimester|follow)\b", re.I)

def ena(acc, timeout=90):
    q = urllib.parse.urlencode({"accession": acc, "result": "read_run", "fields": FIELDS, "format": "tsv"})
    for a in range(3):
        try:
            with urllib.request.urlopen(ENA + "?" + q, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            err = type(e).__name__; time.sleep(2 * (a + 1))
    raise SystemExit("ENA fetch failed for %s (%s)" % (acc, err))

def sites_from(text):
    t = text.lower(); out = []
    for pat, lab in VOCAB:
        if re.search(pat, t) and lab not in out:
            out.append(lab)
    return out

def classify(has_wgs, has_amp, med):
    if has_wgs and med is not None:
        if med >= YES_GBP: return "yes", "%.2f Gbp/sample" % med
        if med >= PARTIAL_GBP: return "partial", "%.2f Gbp/sample (host loss may limit target)" % med
        return "partial", "%.2f Gbp/sample (shallow)" % med
    if has_wgs: return "compute", "shotgun; depth unresolved"
    if has_amp: return "no", "amplicon/16S only"
    return "compute", "assay unclear"

def draft(acc):
    """Derive a MiDAS row dict from ENA structured metadata. Importable by the web API."""
    lines = [l for l in ena(acc).splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    hdr = lines[0].split("\t"); ix = {c: i for i, c in enumerate(hdr)}
    g = lambda f, r: r[ix[f]] if ix.get(f, 99) < len(r) and r[ix[f]] else ""
    strat = {}; sites = []; per_sample = {}; dates = set(); subjects = set()
    timey = human = has_fastq = False
    for ln in lines[1:]:
        r = ln.split("\t")
        st = g("library_strategy", r); strat[st] = strat.get(st, 0) + 1
        txt = g("scientific_name", r) + " | " + g("sample_title", r)
        for s in sites_from(txt):
            if s not in sites: sites.append(s)
        if "human" in txt.lower() or "human" in g("host", r).lower(): human = True
        if TIMEWORDS.search(txt): timey = True
        if g("collection_date", r): dates.add(g("collection_date", r)[:10])
        m = re.search(r"subject[:\s]+(\S+)", g("sample_title", r), re.I)
        if m: subjects.add(m.group(1).strip(",;"))
        if g("fastq_ftp", r): has_fastq = True
        if st.upper() == "WGS":
            bc = g("base_count", r)
            if bc and bc.isdigit():
                k = g("sample_accession", r) or r[0]
                per_sample[k] = per_sample.get(k, 0) + int(bc)
    has_wgs = strat.get("WGS", 0) > 0; has_amp = strat.get("AMPLICON", 0) > 0
    wgs_vals = sorted(v for v in per_sample.values() if v > 0)
    med = (wgs_vals[len(wgs_vals) // 2] / 1e9) if wgs_vals else None
    sc, sc_why = classify(has_wgs, has_amp, med)
    assay = ";".join([a for a, ok in [("16S", has_amp), ("shotgun", has_wgs)] if ok]) or "unknown"
    n_samp = len(per_sample) if per_sample else len(
        {ln.split("\t")[ix["sample_accession"]] for ln in lines[1:] if ix.get("sample_accession", 99) < len(ln.split("\t"))})
    review = ["key_metadata", "16S region", "software/code_url", "cohort"]
    if not sites: review.append("body_sites")
    if not subjects: review.append("n_subjects")
    return {"accession": acc, "runs": len(lines) - 1, "strategy_mix": strat,
            "host": "human" if human else "", "body_sites": sites, "paired_sites": len(sites) >= 2,
            "assay_types": assay, "depth_gbp": med, "strain_capable": sc, "strain_why": sc_why,
            "n_samples": n_samp, "n_subjects": (len(subjects) if subjects else None),
            "longitudinal": "yes" if (timey or len(dates) > 3) else "no?",
            "access": "open" if has_fastq else ("controlled" if acc.lower().startswith("phs") else "embargoed/none-public"),
            "review": review}

def main():
    acc = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: ingest.py <accession> [--append]")
    append = "--append" in sys.argv
    d = draft(acc)
    if not d: sys.exit("no runs for %s" % acc)
    line = lambda tag, f, v: print("  [%-6s] %-16s %s" % (tag, f, v))
    print("\n=== auto-ingest draft: %s ===  (%d runs; strategy mix: %s)" %
          (acc, d["runs"], ", ".join("%s:%d" % kv for kv in d["strategy_mix"].items())))
    line("auto", "accession", acc)
    line("auto", "host", d["host"] or "UNKNOWN")
    line("auto" if d["body_sites"] else "review", "body_sites",
         ";".join(d["body_sites"]) if d["body_sites"] else "UNRESOLVED -> review")
    line("auto", "paired_sites", "yes" if d["paired_sites"] else "no")
    line("auto", "assay_types", d["assay_types"])
    line("auto", "depth/strain", "%s  (%s)" % (d["strain_capable"], d["strain_why"]))
    line("auto", "n_samples", str(d["n_samples"]))
    line("review" if d["n_subjects"] is None else "auto", "n_subjects",
         str(d["n_subjects"]) if d["n_subjects"] is not None else "UNKNOWN (not in metadata)")
    line("auto", "longitudinal", d["longitudinal"])
    line("auto", "access", d["access"])
    print("  --- needs paper / human review ---")
    for f in ["key_metadata (BV/diet/pH/clinical)", "16S region (V3-V4 etc)", "software / code_url", "exact n_subjects + cohort"]:
        print("  [review]  %s" % f)
    if append:
        med = d["depth_gbp"]
        row = ["auto_" + acc, "AUTO-INGEST " + acc, "", "", acc, d["access"], d["host"],
               ";".join(d["body_sites"]), "yes" if d["paired_sites"] else "no", d["longitudinal"], d["assay_types"],
               ("%.2f" % med) if med is not None else "", d["strain_capable"], "%d samples" % d["n_samples"],
               "", "REVIEW", "REVIEW", "REVIEW"]
        path = os.path.join(HERE, "candidates.tsv"); new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8", newline="") as fh:
            if new:
                fh.write("id\tcitation\tpi\tinstitution\taccessions\taccess\thost\tbody_sites\tpaired_sites\tlongitudinal\tassay_types\tdepth\tstrain_capable\tn\tcohort\tkey_metadata\tsoftware\tcode_url\n")
            fh.write("\t".join(row) + "\n")
        print("\nappended draft to candidates.tsv (review gate — not merged into catalog)")

if __name__ == "__main__":
    main()
