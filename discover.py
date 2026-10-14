#!/usr/bin/env python3
"""
MiDAS auto-ingest stages 1-2: DISCOVER + EXTRACT ACCESSIONS.

Stage 1 (discover): query EuropePMC literature search for papers matching a research question.
Stage 2 (extract): pull dataset accessions from each paper's open-access full-text XML
                   (fallback: abstract), via a multi-repo accession regex.
Then optionally (--ingest) run stage-3 ingest.py on each unique BioProject accession to
produce hydrated draft rows in candidates.tsv.

Usage:
  python discover.py "vaginal rectal microbiome metagenome"
  python discover.py "gut vagina axis strain" --n 25
  python discover.py "cervicovaginal shotgun metagenome" --ingest
Stdlib only.
"""
import sys, os, re, json, time, subprocess, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pid}/fullTextXML"
# dataset-level accession patterns across the five repos we see in practice
ACC = re.compile(r"\b(PRJ[EN][AB]\d+|E-MTAB-\d+|GSE\d{3,}|phs\d{6}|[SED]RP\d{6,})\b")
PRJ = re.compile(r"\bPRJ[EN][AB]\d+\b")

def known_accessions():
    """PRJ accessions already in the catalog or already drafted — for de-dup."""
    known = set()
    for fn in ("datasets.tsv", "candidates.tsv"):
        path = os.path.join(HERE, fn)
        if not os.path.exists(path):
            continue
        for ln in open(path, encoding="utf-8"):
            known |= set(PRJ.findall(ln))
    return known

def get(url, timeout=60):
    for a in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(1.5 * (a + 1))
    return ""

def search(query, n):
    # scope to PRIMARY microbiome-sequencing papers that DEPOSITED data (filters out reviews)
    q = ('(%s) AND (metagenom* OR "16S" OR shotgun OR microbiota) '
         'AND (SRA OR BioProject OR ENA OR PRJNA OR PRJEB OR "data availability" OR deposited)') % query
    url = SEARCH + "?" + urllib.parse.urlencode(
        {"query": q, "format": "json", "pageSize": str(n), "resultType": "core"})
    txt = get(url)
    if not txt:
        return []
    try:
        return json.loads(txt).get("resultList", {}).get("result", [])
    except Exception:
        return []

def accessions_for(p):
    """Stage 2: accessions from OA full-text XML, else abstract. Returns set."""
    accs = set()
    pmcid = p.get("pmcid")
    if pmcid:                                   # try full text whenever a PMCID exists (404s are harmless)
        xml = get(FULLTEXT.format(pid=pmcid))
        accs |= set(ACC.findall(xml))
        time.sleep(0.3)
    accs |= set(ACC.findall(p.get("abstractText", "")))
    return accs

def main():
    if len(sys.argv) < 2:
        sys.exit('usage: discover.py "<query>" [--n N] [--ingest]')
    query = sys.argv[1]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 20
    do_ingest = "--ingest" in sys.argv

    print('=== STAGE 1: discover ===  query: "%s"  (EuropePMC, top %d)' % (query, n))
    papers = search(query, n)
    if not papers:
        sys.exit("no results")
    print("found %d papers\n" % len(papers))

    acc2papers = {}            # accession -> [paper short refs]
    with_data = 0
    print("=== STAGE 2: extract accessions ===")
    for p in papers:
        ref = "%s %s %s" % (p.get("authorString", "")[:18], p.get("pubYear", ""), (p.get("journalTitle") or "")[:18])
        accs = accessions_for(p)
        oa = "OA" if p.get("isOpenAccess") == "Y" else "  "
        if accs:
            with_data += 1
            for a in accs:
                acc2papers.setdefault(a, []).append(ref.strip())
        title = (p.get("title") or "")[:62]
        print("  [%s] %-66s %s" % (oa, title, (" ".join(sorted(accs)) if accs else "- (no accession found)")))

    # dedup against the catalog/candidates; prioritize BioProjects (hydratable)
    known = known_accessions()
    allprj = sorted({a for a in acc2papers if PRJ.match(a)})
    new_prj = [a for a in allprj if a not in known]
    dup_prj = [a for a in allprj if a in known]
    other = sorted({a for a in acc2papers if not PRJ.match(a)})
    print("\n=== summary ===")
    print("papers: %d   with an accession: %d   unique accessions: %d" % (len(papers), with_data, len(acc2papers)))
    print("  NEW BioProjects (hydratable): %s" % (", ".join(new_prj) or "none"))
    if dup_prj:
        print("  already in catalog/candidates (skipped): %s" % ", ".join(dup_prj))
    if other:
        print("  other (GEO/dbGaP/arrayexpress/SRP): %s" % ", ".join(other))

    if do_ingest and new_prj:
        print("\n=== STAGE 3 handoff: ingest.py on %d NEW BioProjects ===" % len(new_prj))
        for a in new_prj:
            print("\n--- %s  (from: %s) ---" % (a, "; ".join(acc2papers[a][:2])))
            subprocess.run([sys.executable, os.path.join(HERE, "ingest.py"), a, "--append"])
    elif new_prj:
        print("\n(run with --ingest to hydrate the %d NEW BioProjects into candidates.tsv)" % len(new_prj))
    else:
        print("\n(no new BioProjects to ingest - all already in catalog/candidates)")

if __name__ == "__main__":
    main()
