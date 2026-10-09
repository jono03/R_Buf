"""usage: trace_lookup.py trace.bin lba [lba ...]
Print the firmware-side record(s) for the given start LBAs (fio offset / 4096), to compare with the host latency of the same read."""
import sys
import trace_parse as t

h, recs = t.load(sys.argv[1])
unit = (1 << h["timeShift"]) * 1000.0 / h["countsPerSecond"]
want = set(int(x) for x in sys.argv[2:])
for r in recs:
    if r["lba"] in want:
        s = t.segments(r, None)
        print("lba=%d seq=%d fw_total=%.3f ms  buffer=%.3f dieq=%.3f loop=%.3f xferwait=%.3f nanddma=%.3f  flags=0x%04x" % (
            r["lba"], r["seq"], r["dDmaEnd"] * unit, s["buffer"] * unit, s["dieq"] * unit, s["loop"] * unit,
            s["xferwait"] * unit, s["nanddma"] * unit, r["flags"]))
