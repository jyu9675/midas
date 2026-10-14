#!/usr/bin/env python3
"""
MiDAS: promote a reviewed auto-ingest candidate into the curated catalog.

candidates.tsv is the review gate (auto-drafted rows). Once a row is reviewed/enriched,
`promote` assigns it the next dataset id (dNN), appends it to datasets.tsv, and removes it
from candidates.tsv. A readiness check blocks promotion of rows that still have auto-ingest
placeholders (override with --force). After promoting, re-run hydrate_depth.py + test_resolver.py.

Usage:
  python promote.py --list                 # candidates + readiness
  python promote.py auto_PRJNA826539        # promote one (if ready)
  python promote.py auto_PRJNA826539 --force
"""
import sys, os, csv, re

HERE = os.path.dirname(os.path.abspath(__file__))
CAND = os.path.join(HERE, "candidates.tsv")
CAT = os.path.join(HERE, "datasets.tsv")

def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    return rows[0], rows[1:]

def readiness(row, ix):
    """Return list of unresolved fields that should be filled before promotion."""
    bad = []
    g = lambda f: row[ix[f]] if ix.get(f, 99) < len(row) else ""
    if not g("citation") or g("citation").startswith("AUTO-INGEST"): bad.append("citation")
    if not g("body_sites") or "UNRESOLVED" in g("body_sites"): bad.append("body_sites")
    if g("assay_types") in ("", "unknown"): bad.append("assay_types")
    if g("software") in ("", "REVIEW"): bad.append("software")
    if g("key_metadata") in ("", "REVIEW"): bad.append("key_metadata")
    return bad

def next_id(cat_rows, ix):
    n = 0
    for r in cat_rows:
        m = re.match(r"d(\d+)$", r[ix["id"]])
        if m: n = max(n, int(m.group(1)))
    return "d%02d" % (n + 1)

def main():
    if not os.path.exists(CAND):
        sys.exit("no candidates.tsv")
    chdr, crows = load(CAND); cix = {c: i for i, c in enumerate(chdr)}
    thdr, trows = load(CAT); tix = {c: i for i, c in enumerate(thdr)}

    if "--list" in sys.argv or len(sys.argv) < 2:
        print("=== candidates (review gate) ===")
        for r in crows:
            bad = readiness(r, cix)
            print("  %-22s %-14s %s" % (r[cix["id"]], r[cix["accessions"]],
                  "READY" if not bad else "needs: " + ", ".join(bad)))
        print("\npromote with: python promote.py <id> [--force]")
        return

    cid = sys.argv[1]; force = "--force" in sys.argv
    match = [r for r in crows if r[cix["id"]] == cid]
    if not match:
        sys.exit("candidate %s not found (see --list)" % cid)
    row = match[0]
    bad = readiness(row, cix)
    if bad and not force:
        sys.exit("NOT READY - unresolved fields: %s\n  enrich first (python enrich.py %s --write) "
                 "or override with --force" % (", ".join(bad), row[cix["accessions"]].split(";")[0]))

    # candidate columns are a superset-compatible match to the catalog schema; map by name
    new = [""] * len(thdr)
    nid = next_id(trows, tix)
    for col in thdr:
        new[tix[col]] = row[cix[col]] if col in cix and cix[col] < len(row) else ""
    new[tix["id"]] = nid

    with open(CAT, "a", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(new) + "\n")
    remaining = [r for r in crows if r[cix["id"]] != cid]
    with open(CAND, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(chdr) + "\n")
        for r in remaining:
            fh.write("\t".join(r) + "\n")

    print("promoted %s -> %s in datasets.tsv  (%s)%s" %
          (cid, nid, row[cix["accessions"]], "  [--force: had unresolved %s]" % ",".join(bad) if bad else ""))
    print("next: python hydrate_depth.py  &&  python test_resolver.py   (refresh depth + verify)")

if __name__ == "__main__":
    main()
