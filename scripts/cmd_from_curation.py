#!/usr/bin/env python3
"""Build a curatedMetagenomicData sampleMetadata TSV WITHOUT R.

cMD's harmonized metadata normally comes from the R package (`sampleMetadata`), but the per-study
curated tables live in the public curation repo as `inst/curated/<Study>/<Study>_sample.tsv`. This
fetches a set of studies and concatenates them (union of columns) into one TSV that MiDAS's `cmd`
adapter reads via MIDAS_CMD_TSV — so cMD works with no R install.

Usage:
  python scripts/cmd_from_curation.py                       # a default human-gut set
  python scripts/cmd_from_curation.py AsnicarF_2017 NielsenHB_2014 ...   # specific studies
  python scripts/cmd_from_curation.py --out cmd_sampleMetadata.tsv
Then:
  MIDAS_CMD_TSV=cmd_sampleMetadata.tsv python crossrepo.py "inflammatory bowel disease" --repos cmd
(Study names: https://github.com/waldronlab/curatedMetagenomicDataCuration/tree/master/inst/curated)
"""
import csv
import io
import sys
import urllib.request

BASE = "https://raw.githubusercontent.com/waldronlab/curatedMetagenomicDataCuration/master/inst/curated"
DEFAULT = ["AsnicarF_2017", "BackhedF_2015", "BedarfJR_2017", "VatanenT_2016", "NielsenHB_2014"]


def main(argv):
    out = "cmd_sampleMetadata.tsv"
    studies = []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = next(it)
        else:
            studies.append(a)
    studies = studies or DEFAULT

    rows, cols = [], []
    for s in studies:
        try:
            txt = urllib.request.urlopen(f"{BASE}/{s}/{s}_sample.tsv", timeout=60).read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  skip {s}: {type(e).__name__}", file=sys.stderr)
            continue
        rd = list(csv.DictReader(io.StringIO(txt), delimiter="\t"))
        for c in (rd[0].keys() if rd else []):
            if c not in cols:
                cols.append(c)
        rows.extend(rd)
        print(f"  {s}: {len(rd)} samples")
    if not rows:
        print("no studies fetched", file=sys.stderr)
        return 1
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}: {len(rows)} samples x {len(cols)} cols, "
          f"{len({r.get('study_name') for r in rows})} studies -> set MIDAS_CMD_TSV={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
