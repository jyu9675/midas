#!/usr/bin/env python3
"""
MiDAS auto-ingest stage 4: ENRICH the paper-only residue of a candidate row.

Given an accession, find its paper (EuropePMC), then fill the fields the repository APIs
can't: citation, software/pipelines, code URL, 16S region, clinical key_metadata, cohort,
n_subjects. A DETERMINISTIC backbone (regex + dictionaries, stdlib) does most of it; an
OPTIONAL LLM pass (official `anthropic` SDK, model claude-opus-5) refines the fuzzy fields
IF the SDK + credentials are present — otherwise it degrades gracefully to deterministic-only.

Usage:
  python enrich.py PRJNA288562
  python enrich.py PRJEB50325 --write      # update the matching row in candidates.tsv
  MIDAS_LLM_MODEL=claude-sonnet-5 python enrich.py PRJNA826539   # cheaper LLM
Core is stdlib; LLM pass needs `pip install anthropic` + ANTHROPIC_API_KEY (or `ant auth login`).
"""
import sys, os, re, json, time, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# ---- deterministic dictionaries ----
SOFTWARE = ["DADA2", "QIIME2", "QIIME", "mothur", "VSEARCH", "USEARCH", "MetaPhlAn", "HUMAnN",
            "inStrain", "StrainPhlAn", "StrainFacts", "VALENCIA", "VIRGO2", "VIRGO", "Kraken2",
            "Kraken", "Bracken", "Bowtie2", "BWA", "SPAdes", "MEGAHIT", "Prokka", "Bakta",
            "Panaroo", "PHLAME", "CheckM", "dRep", "DESeq2", "ANCOM-BC", "ANCOM", "LEfSe",
            "phyloseq", "vegan", "MaAsLin2", "MaAsLin", "CroCoDeEL", "GTDB-Tk", "fastp", "cutadapt",
            "Trimmomatic", "PropagAtE", "VAMB", "STAR", "Salmon", "sickle", "RAxML", "FastTree", "IQ-TREE"]
META = [(r"bacterial vaginosis|\bBV\b|nugent|amsel", "BV/Nugent"), (r"diet|dietary|nutrition", "diet"),
        (r"\bpH\b|vaginal pH", "pH"), (r"\bHIV\b", "HIV"), (r"menstrual|menses|menstruation|cycle phase", "menses"),
        (r"contracepti|DMPA|NET-EN|\bIUD\b|hormonal", "contraception"), (r"antibiotic|metronidazole|azithromycin", "antibiotics"),
        (r"gestational|pregnan|trimester|preterm|postpartum", "pregnancy/gestation"),
        (r"ethnic|race|demographic|\bage\b", "demographics"), (r"timepoint|time point|longitudinal|week \d|day \d|visit", "timepoints"),
        (r"\bSTI\b|chlamydia|gonorrh|trichomonas|HPV", "STI")]
CODE = re.compile(r"github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+|(?:10\.5281/)?zenodo\.(?:org/record/)?\d+", re.I)
REGION = re.compile(r"\bV\d\s?[-–]\s?V?\d\b|\bV\d\b(?=\s*(region|hypervariable|rRNA|amplicon))", re.I)
PRIMER = [(r"515F|806R|GTGYCAGC", "V4"), (r"341F|805R|CCTACGGG", "V3-V4"), (r"27F|338R", "V1-V2"), (r"967F|1046R", "V6")]

def get(url, timeout=60):
    for a in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(1.5 * (a + 1))
    return ""

def find_paper(acc):
    """EuropePMC: the paper that reports this accession."""
    url = EPMC + "/search?" + urllib.parse.urlencode(
        {"query": '"%s"' % acc, "format": "json", "pageSize": "3", "resultType": "core"})
    try:
        res = json.loads(get(url)).get("resultList", {}).get("result", [])
    except Exception:
        res = []
    return res[0] if res else None

def strip_xml(x):
    x = re.sub(r"<[^>]+>", " ", x)
    return re.sub(r"\s+", " ", x)

def deterministic(text, paper):
    t = text
    soft = [s for s in SOFTWARE if re.search(r"\b" + re.escape(s) + r"\b", t)]
    # de-dup near-duplicates (QIIME2 implies QIIME; MetaPhlAn etc. fine)
    meta = [lab for pat, lab in META if re.search(pat, t, re.I)]
    code = sorted(set(m.group(0) for m in CODE.finditer(t)))[:3]
    region = ""
    m = REGION.search(t)
    if m: region = m.group(0).replace(" ", "")
    if not region:
        for pat, reg in PRIMER:
            if re.search(pat, t, re.I): region = reg; break
    cite = ""
    if paper:
        au = (paper.get("authorString") or "").split(",")[0]
        jrnl = paper.get("journalTitle") or (((paper.get("journalInfo") or {}).get("journal") or {}).get("title")) or ""
        cite = ("%s %s %s" % (au, paper.get("pubYear", ""), jrnl)).strip()
    return {"citation": cite, "software": sorted(set(soft)), "code_url": code,
            "region_16S": region, "key_metadata": meta}

def llm_refine(text, det):
    """Optional: refine fuzzy fields via Claude. Returns {} if SDK/creds absent."""
    try:
        import anthropic
    except ImportError:
        print("  [llm] anthropic SDK not installed -> deterministic-only (pip install anthropic)")
        return {}
    try:
        client = anthropic.Anthropic()
    except Exception as e:
        print("  [llm] no credentials -> deterministic-only (%s)" % type(e).__name__)
        return {}
    model = os.environ.get("MIDAS_LLM_MODEL", "claude-opus-5")
    body = text if len(text) < 60000 else text[:60000]
    if len(text) >= 60000:
        print("  [llm] note: paper text capped at 60k chars for the extraction call")
    prompt = ("From this microbiome paper, extract ONLY what is stated, as a JSON object with keys: "
              "n_subjects (integer or null), cohort (short phrase, e.g. 'South African women 18-23'), "
              "key_metadata (list of clinical/sample variables actually measured, e.g. BV, diet, pH, HIV), "
              "region_16S (e.g. 'V3-V4', or null if shotgun-only), software (list of bioinformatics tools). "
              "Return JSON only, no prose.\n\nPAPER:\n" + body)
    try:
        r = client.messages.create(model=model, max_tokens=8000,
                                    thinking={"type": "adaptive"},
                                    messages=[{"role": "user", "content": prompt}])
    except Exception as e:
        why = "no ANTHROPIC_API_KEY / credentials" if "authentication" in str(e).lower() else type(e).__name__
        print("  [llm] skipped -> deterministic-only (%s)" % why)
        return {}
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        print("  [llm] no JSON in response -> deterministic-only")
        return {}
    try:
        out = json.loads(m.group(0))
        print("  [llm] refined via %s" % model)
        return out
    except Exception:
        print("  [llm] JSON parse failed -> deterministic-only")
        return {}

def main():
    if len(sys.argv) < 2:
        sys.exit("usage: enrich.py <accession> [--write]")
    acc = sys.argv[1]; write = "--write" in sys.argv
    print("=== STAGE 4: enrich residue for %s ===" % acc)
    paper = find_paper(acc)
    if paper:
        print("  paper: %s" % ((paper.get("title") or "")[:72]))
    text = ""
    if paper and paper.get("pmcid"):
        text = strip_xml(get(EPMC + "/%s/fullTextXML" % paper["pmcid"]))
    if len(text) < 500 and paper:
        text = paper.get("abstractText", "")
        print("  (no OA full text; using abstract only)")
    det = deterministic(text, paper)
    llm = llm_refine(text, det) if text else {}

    # merge: deterministic backbone, LLM refines fuzzy fields where it returned something
    merged = dict(det)
    for k in ("n_subjects", "cohort"):
        if llm.get(k) not in (None, "", []): merged[k] = llm[k]
    for k in ("key_metadata", "software"):
        if llm.get(k):
            merged[k] = sorted(set(list(det.get(k, [])) + list(llm[k])))
    if llm.get("region_16S") and not merged.get("region_16S"):
        merged["region_16S"] = llm["region_16S"]

    print("\n  citation     : %s" % merged.get("citation", ""))
    print("  cohort       : %s" % merged.get("cohort", "(deterministic: n/a; needs LLM)"))
    print("  n_subjects   : %s" % merged.get("n_subjects", "(needs LLM)"))
    print("  16S region   : %s" % (merged.get("region_16S") or "(shotgun or not found)"))
    print("  key_metadata : %s" % "; ".join(merged.get("key_metadata", [])))
    print("  software     : %s" % "; ".join(merged.get("software", [])))
    print("  code_url     : %s" % "; ".join(merged.get("code_url", [])))

    if write:
        path = os.path.join(HERE, "candidates.tsv")
        if not os.path.exists(path):
            print("\n  (no candidates.tsv to update)"); return
        rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
        hdr = rows[0]; ix = {c: i for i, c in enumerate(hdr)}
        rid = "auto_" + acc; updated = False
        for r in rows[1:]:
            if r and r[0] == rid:
                r[ix["citation"]] = merged.get("citation", r[ix["citation"]])
                r[ix["key_metadata"]] = "; ".join(merged.get("key_metadata", [])) or "REVIEW"
                r[ix["software"]] = "; ".join(merged.get("software", [])) or "REVIEW"
                r[ix["code_url"]] = "; ".join(merged.get("code_url", [])) or ""
                if merged.get("cohort"): r[ix["cohort"]] = merged["cohort"]
                updated = True
        if updated:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write("\n".join("\t".join(r) for r in rows) + "\n")
            print("\n  updated %s in candidates.tsv" % rid)
        else:
            print("\n  (%s not in candidates.tsv; run discover/ingest --ingest first)" % rid)

if __name__ == "__main__":
    main()
