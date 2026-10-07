#!/usr/bin/env python3
"""Paper-style E1 table from fio normal-format output.

usage: e1_table.py sbuf_ro.txt sbuf_mix.txt rbuf_ro.txt rbuf_mix.txt
  <x>_ro  : read-only run   (e1.sh: <tag>_ro4.txt or <tag>_ro2.txt)
  <x>_mix : read+write run  (e1.sh: <tag>_mix.txt)
Prints, per build: read-latency multiple (mixed mean / read-only mean),
read IOPS, read p95, write IOPS, and S-Buf -> R-Buf changes next to the paper values
(An et al., PVLDB 2022: multiple 8.8 -> 1.1, read IOPS 5.4K -> 28.1K, p95 133 -> 9 ms,
write IOPS 5349 -> 4156).
"""
import re, sys

UNIT = {"nsec": 1e-3, "usec": 1.0, "msec": 1e3, "sec": 1e6}

def num(s):
    s = s.strip()
    m = re.fullmatch(r"([\d.]+)([kM]?)", s)
    v = float(m.group(1))
    return v * {"": 1, "k": 1e3, "M": 1e6}[m.group(2)]

def parse(path):
    """-> {'read': {...}, 'write': {...}} ; IOPS summed, clat mean IOPS-weighted, pcts averaged."""
    blocks = []
    cur = None
    unit = None
    for line in open(path, errors="replace"):
        m = re.match(r"\s+(read|write):\s+IOPS=([\d.]+[kM]?)", line)
        if m:
            cur = {"dir": m.group(1), "iops": num(m.group(2)), "avg": None, "pct": {}}
            blocks.append(cur)
            unit = None
            continue
        if cur is None:
            continue
        m = re.match(r"\s+clat \((\w+)\):.*avg=\s*([\d.]+)", line)
        if m and cur["avg"] is None:
            cur["avg"] = float(m.group(2)) * UNIT[m.group(1)]
            continue
        m = re.match(r"\s+clat percentiles \((\w+)\)", line)
        if m and not cur["pct"]:
            unit = UNIT[m.group(1)]
            continue
        if unit and "th=[" in line:
            for p, v in re.findall(r"(\d+(?:\.\d+)?)th=\[\s*(\d+)\]", line):
                cur["pct"][float(p)] = float(v) * unit
        elif unit and cur["pct"] and "th=[" not in line and not line.strip().startswith("|"):
            unit = None
    out = {}
    for d in ("read", "write"):
        bs = [b for b in blocks if b["dir"] == d and b["avg"] is not None]
        if not bs:
            continue
        iops = sum(b["iops"] for b in bs)
        avg = sum(b["avg"] * b["iops"] for b in bs) / iops
        pct = {}
        for p in set().union(*[b["pct"].keys() for b in bs]):
            vals = [b["pct"][p] for b in bs if p in b["pct"]]
            pct[p] = sum(vals) / len(vals)
        out[d] = {"iops": iops, "avg": avg, "pct": pct, "n": len(bs)}
    return out

def summarize(ro, mix):
    r_ro, r_mx, w_mx = ro["read"], mix["read"], mix.get("write")
    return {
        "mult": r_mx["avg"] / r_ro["avg"],
        "r_iops": r_mx["iops"],
        "p95_ms": r_mx["pct"].get(95.0, float("nan")) / 1e3,
        "w_iops": w_mx["iops"] if w_mx else float("nan"),
    }

def pct_change(a, b):
    return (b - a) / a * 100.0

if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    s = summarize(parse(sys.argv[1]), parse(sys.argv[2]))
    r = summarize(parse(sys.argv[3]), parse(sys.argv[4]))
    rows = [
        ("read latency multiple (mixed/read-only mean)", "%.1fx" % s["mult"], "%.1fx" % r["mult"], "8.8x -> 1.1x"),
        ("read IOPS (mixed)", "%.0f" % s["r_iops"], "%.0f (%+.0f%%)" % (r["r_iops"], pct_change(s["r_iops"], r["r_iops"])), "5.4K -> 28.1K (+420%)"),
        ("read p95 (mixed)", "%.1f ms" % s["p95_ms"], "%.1f ms (%+.0f%%)" % (r["p95_ms"], pct_change(s["p95_ms"], r["p95_ms"])), "133 -> 9 ms (-93%)"),
        ("write IOPS (mixed)", "%.0f" % s["w_iops"], "%.0f (%+.0f%%)" % (r["w_iops"], pct_change(s["w_iops"], r["w_iops"])), "5349 -> 4156 (-22%)"),
    ]
    w0 = max(len(x[0]) for x in rows)
    print("%-*s | %-12s | %-20s | %s" % (w0, "metric", "S-Buf", "R-Buf (change)", "paper S-Buf -> R-Buf"))
    for a, b, c, d in rows:
        print("%-*s | %-12s | %-20s | %s" % (w0, a, b, c, d))
    print("\nnote: multiple uses clat means; one long stall can dominate it - also compare p95/p99.")
