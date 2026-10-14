#!/usr/bin/env python3
"""
MiDAS - Microbiome Data & Analysis Search (resolver MVP)

Given a research question, resolve the biologically-compatible datasets + the executable
analysis stack, from datasets.tsv using the rules in schema.yaml. Stdlib only (runs anywhere).

Usage:
  python midas.py                      # milestone-1 demo: run all three sub-questions
  python midas.py "cross-site strain sharing with diet"   # free-text -> detected question(s)
  python midas.py --q strain           # strain | diet | ecology
  python midas.py --list               # dump the catalog
"""
import csv, os, sys, re

HERE = os.path.dirname(os.path.abspath(__file__))
TSV = os.path.join(HERE, "datasets.tsv")

# ---- pipeline registry (schema.yaml) ----
PIPELINES = {
    "shotgun_strain":  ["inStrain", "StrainPhlAn", "StrainFacts", "strainshare"],
    "shotgun_compose": ["MetaPhlAn", "HUMAnN"],
    "16S_compose":     ["DADA2", "QIIME2"],
    "vaginal_CST":     ["VALENCIA", "VIRGO2"],
    "contamination_qc":["CroCoDeEL", "strainshare"],
}

# ---- parsing helpers (fields carry ';' lists and parenthetical sub-annotations) ----
def split_top(s):
    """split on ';' but NOT inside parentheses: 'cervix(a;b);gut' -> ['cervix(a;b)','gut']"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1; cur += ch
        elif ch == ")":
            depth -= 1; cur += ch
        elif ch == ";" and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out

def base(tok):
    return re.sub(r"\(.*?\)", "", tok).strip()          # 'partial(shallow)' -> 'partial'

def body_sites(row):
    return [base(x) for x in split_top(row["body_sites"])]

def assays(row):
    return [base(x) for x in split_top(row["assay_types"])]

def has_assay(row, *keys):
    a = " ".join(assays(row)).lower()
    return any(k.lower() in a for k in keys)

def strain_level(row):
    return base(row["strain_capable"]).lower()          # yes|partial|no|compute

def access_rank(row):
    a = row["access"].lower()
    if "request-only" in a or a == "none":
        return 2, "NO DATA (request-only)"
    if "open" in a and "controlled" not in a and "token" not in a:
        return 0, "open"
    if a == "open" or "open(" in a:
        return 0, "open"
    return 1, "gated (" + row["access"] + ")"

def diet_meta(row):
    return "diet" in row["key_metadata"].lower()

# ---- the resolver rules (schema.yaml: question -> required data-profile) ----
def match_strain_sharing(row):
    sites = [s for s in body_sites(row) if s not in ("", "resource")]
    distinct = len(set(sites))
    ok_sites = distinct >= 2                                   # >=2 distinct body sites
    ok_assay = has_assay(row, "shotgun", "isolate-WGS", "long-read", "isolate")
    ok_strain = strain_level(row) in ("yes", "partial", "compute")   # compute = depth unverified, still a candidate
    if ok_sites and ok_assay and ok_strain:
        why = "%d body sites; %s; strain=%s" % (distinct, "+".join(sorted(set(sites))), strain_level(row))
        return True, why
    return False, ""

def match_diet(row):
    if diet_meta(row) and has_assay(row, "16S", "shotgun"):
        return True, "diet metadata present; " + "+".join(assays(row))
    return False, ""

def match_ecology(row):
    sites = " ".join(body_sites(row)).lower()
    if ("vagin" in sites or "cervi" in sites) and has_assay(row, "16S", "shotgun", "catalog"):
        return True, "vaginal/cervical; " + "+".join(assays(row))
    return False, ""

QUESTIONS = {
    "strain":  ("cross-site strain sharing", match_strain_sharing),
    "diet":    ("diet <-> microbiome",        match_diet),
    "ecology": ("vaginal microbial ecology",  match_ecology),
}

def recommend(row, qkey):
    recs = []
    if qkey == "strain":
        recs += PIPELINES["shotgun_strain"] + PIPELINES["contamination_qc"]
    elif qkey == "diet":
        recs += (PIPELINES["shotgun_compose"] if has_assay(row, "shotgun") else PIPELINES["16S_compose"])
        recs += ["MaAsLin2/association-stats"]
    elif qkey == "ecology":
        recs += PIPELINES["vaginal_CST"] + (PIPELINES["16S_compose"] if has_assay(row, "16S") else PIPELINES["shotgun_compose"])
    seen = []
    for r in recs:
        if r not in seen:
            seen.append(r)
    return seen

def load():
    # prefer the depth-hydrated catalog (data-backed strain_capable) if present
    path = os.path.join(HERE, "datasets_hydrated.tsv")
    if not os.path.exists(path):
        path = TSV
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8"), delimiter="\t"))
    for r in rows:
        if r.get("strain_capable_hydrated"):           # use computed call, keep depth for display
            r["strain_capable"] = r["strain_capable_hydrated"]
    return rows

def resolve(rows, qkey):
    name, fn = QUESTIONS[qkey]
    hits = []
    for r in rows:
        ok, why = fn(r)
        if ok:
            rank, acc = access_rank(r)
            hits.append((rank, r, why, acc))
    # rank: open first; then strain yes>partial; then shotgun>16S
    hits.sort(key=lambda h: (h[0],
                             0 if strain_level(h[1]) == "yes" else 1,
                             0 if has_assay(h[1], "shotgun", "isolate-WGS") else 1))
    print("\n=== QUESTION: %s ===  (%d compatible datasets)" % (name, len(hits)))
    for rank, r, why, acc in hits:
        mark = {0: "[OK ]", 1: "[gated]", 2: "[no-data]"}[rank]
        caveat = ""
        if qkey == "strain":
            sl = strain_level(r); d = r.get("depth_gbp_median", "")
            if sl == "partial":
                caveat = "  <- CAVEAT: strain=partial" + (" (%s Gbp/sample raw; host loss may drop target <10x)" % d if d else "")
            elif sl == "compute":
                caveat = "  <- VERIFY: depth unresolved via ENA (new/controlled) - confirm before trusting"
        print("  %s %-4s %-34s %-22s %s%s" % (mark, r["id"], r["citation"][:34], r["accessions"].split(";")[0], why, caveat))
        print("          access: %s   ->  stack: %s" % (acc, ", ".join(recommend(r, qkey))))
    return hits

def detect(text):
    t = text.lower()
    qs = []
    if re.search(r"strain|shar|transmiss|cross.?site|reservoir", t): qs.append("strain")
    if re.search(r"diet|nutri|food", t): qs.append("diet")
    if re.search(r"ecolog|composition|\bcst\b|community|vaginal ecology", t): qs.append("ecology")
    return qs or list(QUESTIONS)

def main():
    rows = load()
    args = sys.argv[1:]
    if args and args[0] == "--list":
        for r in rows:
            print("%-4s %-36s %-26s %s" % (r["id"], r["citation"][:36], r["accessions"].split(";")[0], r["access"]))
        return
    if args and args[0] == "--q":
        qs = [args[1]]
    elif args:
        qs = detect(" ".join(args))
    else:
        print("MiDAS milestone-1 demo  |  catalog: %d datasets  |  query: "
              "'public datasets to combine with multi-site rectal-vaginal data for\n"
              "cross-site strain sharing, diet, or vaginal ecology?'" % len(rows))
        qs = ["strain", "diet", "ecology"]
    for q in qs:
        if q in QUESTIONS:
            resolve(rows, q)
        else:
            print("unknown question '%s' (use: strain|diet|ecology)" % q)
    print()

if __name__ == "__main__":
    main()
