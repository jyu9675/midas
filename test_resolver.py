#!/usr/bin/env python3
"""Hard-assert the resolver's biological truths. Run: python test_resolver.py"""
import io, sys, contextlib
import midas

rows = midas.load()
def ids(q):
    with contextlib.redirect_stdout(io.StringIO()):     # resolve() also prints; silence it
        hits = midas.resolve(rows, q)
    return [r["id"] for _, r, _, _ in hits]

s = ids("strain"); d = ids("diet"); e = ids("ecology")

# cross-site strain sharing: needs >=2 body sites + shotgun/isolate + strain-capable
assert "d28" in s, "Goltsman (3-site shotgun) must resolve for strain sharing"
assert "d30" in s, "MOMS-PI (rectum+vagina) must resolve (compute=verify, still a candidate)"
assert "d10" not in s, "Hussain is donor-recipient (1 body site) = cross-person, NOT cross-site"
assert "d03" not in s and "d07" not in s, "16S-only datasets can never do strain resolution"

# diet: datasets carrying diet metadata (Rocafort 24h recall + Krog/MiMens)
assert "d07" in d and "d33" in d, "Rocafort + Krog (diet metadata) should match diet; got %s" % d

# the added paired vaginal+rectal shotgun cohorts must resolve for strain sharing
assert "d35" in s, "Bommana (cervix+vagina+rectum shotgun) must resolve for strain sharing"
assert "d33" in s and "d34" in s, "Krog + Sterpu (paired vaginal+rectal shotgun) must resolve"

# ecology: vaginal 16S/shotgun; includes the VIRGO resource; request-only shown but ranked last
assert "d29" in e and "d28" in e, "VIRGO + Goltsman should match vaginal ecology"
assert "d10" in e, "request-only vaginal set still surfaces (as no-data) for ecology"
assert e.index("d10") > e.index("d29"), "no-data rows must rank below open rows"

# hydrated depth wired in: Goltsman is partial with a real depth number
g = [r for r in rows if r["id"] == "d28"][0]
assert g["strain_capable"] == "partial" and g.get("depth_gbp_median") == "0.35", \
    "Goltsman should carry the computed 0.35 Gbp -> partial call"

print("ALL RESOLVER TESTS PASS  (strain=%d, diet=%d, ecology=%d compatible)" % (len(s), len(d), len(e)))
