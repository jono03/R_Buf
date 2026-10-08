#!/usr/bin/env python3
"""Parse a firmware trace dump (trace_log.c) into a CSV and print a segment summary.

usage: trace_parse.py trace.bin [--csv out.csv] [--stall-ms 1000] [--fio-log a_clat.log [--fio-log b_clat.log ...]]
                      [--nand-ms 0.3] [--die-ms 0.57]

trace.bin = raw memory dump starting at TRACE_BASE_ADDR (0x00300000): 4KB header + 64B records
(see tools/trace_dump.md). Segments follow team-experiment-procedure 12.2:

  buffer   = dEnqueue - dBufAlloc                (buffer entry wait, incl. eviction / row-address dependency)
  dieq     = max(0, dDieLastDone - dEnqueue)     (waiting for the previous request on that die)
  loop     = dBufAlloc + (dIssue - max(dEnqueue, dDieLastDone)) + (dDmaStart - dNandDone)
  xferwait = dXferIssue - dTrigDone              (read transfer waits behind other channel work)
  nanddma  = (dTrigDone - dIssue) + (dNandDone - dXferIssue) + (dDmaEnd - dDmaStart)

Two views are printed. The primary view follows the team decomposition rule exactly (trigger, transfer and DMA time
all count as nanddma; the polling caveat is a stated limitation). The secondary "polling-adjusted" view is NOT part of
the pre-fixed rule: completion is only noticed when the main loop runs the scheduler, so any part of
(dTrigDone - dIssue), (dNandDone - dXferIssue) and the host DMA time above --nand-ms (default 0.3 ms, about the whole
read-only latency; an assumption, tune it) is reported as "loop" instead of "nanddma".
The die-queue wait is flagged "dieq-suspect" when it exceeds 3 x (aheadCnt+1) x --die-ms (default 0.57 ms = one program per die at 14K IOPS / 8 dies).
schedTrig / schedXfer = number of SchedulingNandReq() calls during the trigger / transfer wait: a long wait with
almost no calls means the loop did not poll (case B); many calls with a long wait means the NAND/die was really busy.

Host matching (--fio-log): fio read latency logs (write_lat_log, log_offset=1: time_ms, latency_ns, dir, bs, offset)
are matched to records by order + LBA (offset = lba * 4096). host latency - firmware total = "fetch before"
(time before the firmware took the command). A host stall with a short firmware time is case N2.

Records without NAND access (buffer hit / unmapped, flags b0/b4): buffer = dDmaStart - dBufAlloc.
'fetch before' (host latency minus firmware time) needs the fio log and is not computed here.
"""
import struct
import sys

HDR_FMT = "<19I"
HDR_NAMES = ["magic", "version", "recCount", "stopFlag", "rbuf", "trace", "verify", "rbufEntries",
             "countsPerSecond", "timeShift", "maxRecords", "recBytes", "recOffset", "gcCnt",
             "bufEvictCnt", "bufReadEvictCnt", "rbufReadAllocCnt", "rbufWriteHitInvalidateCnt", "dropped"]
REC_FMT = "<IIQ7iHHiiHH4s"
REC_NAMES = ["seq", "lba", "tFetch", "dBufAlloc", "dEnqueue", "dDieLastDone", "dIssue", "dNandDone",
             "dDmaStart", "dDmaEnd", "flags", "aheadCnt", "dXferIssue", "dTrigDone", "schedTrig", "schedXfer", "pad"]
MAGIC = 0x45435254

assert struct.calcsize(REC_FMT) == 64


def load(path):
    data = open(path, "rb").read()
    h = dict(zip(HDR_NAMES, struct.unpack_from(HDR_FMT, data, 0)))
    if h["magic"] != MAGIC:
        sys.exit("bad magic 0x%08X (expected 0x%08X): wrong dump address/size?" % (h["magic"], MAGIC))
    if h["version"] not in (2, 3):
        sys.exit("unsupported trace format version %d" % h["version"])
    if h["recBytes"] != 64:
        sys.exit("unexpected record size %d" % h["recBytes"])
    n = h["recCount"]
    need = h["recOffset"] + n * 64
    if len(data) < need:
        print("warning: dump has %d bytes but header says %d records (%d bytes); using what is there"
              % (len(data), n, need), file=sys.stderr)
        n = max(0, (len(data) - h["recOffset"]) // 64)
    recs = []
    for i in range(n):
        v = struct.unpack_from(REC_FMT, data, h["recOffset"] + i * 64)
        d = dict(zip(REC_NAMES, v))
        if h["version"] < 3:
            d["schedTrig"] = d["schedXfer"] = 0
        recs.append(d)
    return h, recs


def segments(r, nand_ticks):
    """segment lengths in ticks (units of 2**timeShift XTime counts)
    nand_ticks = None: team rule (everything counts as nanddma). Otherwise the part of trigger / transfer / DMA
    time above nand_ticks is moved to loop (secondary, polling-adjusted view)"""
    if nand_ticks is None:
        nand_ticks = 1 << 62
    flags = r["flags"]
    seg = dict(buffer=0, dieq=0, loop=0, xferwait=0, nanddma=0)
    if flags & (0x0001 | 0x0010):              # buffer hit or unmapped: no NAND request
        dma = max(0, r["dDmaEnd"] - r["dDmaStart"])
        seg["loop"] = r["dBufAlloc"] + max(0, dma - nand_ticks)
        seg["buffer"] = max(0, r["dDmaStart"] - r["dBufAlloc"])
        seg["nanddma"] = min(dma, nand_ticks)
        return seg
    start = max(r["dEnqueue"], r["dDieLastDone"])
    trig = max(0, r["dTrigDone"] - r["dIssue"])
    xfer = max(0, r["dNandDone"] - r["dXferIssue"])
    dma = max(0, r["dDmaEnd"] - r["dDmaStart"])
    seg["loop"] = (r["dBufAlloc"] + max(0, r["dIssue"] - start) + max(0, r["dDmaStart"] - r["dNandDone"])
                   + max(0, trig - nand_ticks) + max(0, xfer - nand_ticks) + max(0, dma - nand_ticks))
    seg["buffer"] = max(0, r["dEnqueue"] - r["dBufAlloc"])
    seg["dieq"] = max(0, r["dDieLastDone"] - r["dEnqueue"])
    seg["xferwait"] = max(0, r["dXferIssue"] - r["dTrigDone"])
    seg["nanddma"] = min(trig, nand_ticks) + min(xfer, nand_ticks) + min(dma, nand_ticks)
    return seg


def load_fio(paths):
    """fio lat logs -> list of (time_ms, latency_ms, offset); completion order inside each file, files in argument order"""
    out = []
    for path in paths:
        part = []
        for line in open(path):
            f = [x.strip() for x in line.split(",")]
            if len(f) < 5 or not f[0].isdigit():
                continue
            if f[2] != "0":                      # direction 0 = read
                continue
            part.append((int(f[0]), int(f[1]) / 1e6, int(f[4])))
        part.sort()          # sort inside one file only: each fio job log has its own clock
        out.extend(part)     # files are used in the order given on the command line (ro first, then reader)
    return out


def match_fio(rows, fio):
    """order + LBA matching; returns {seq: host_latency_ms}"""
    by_lba = {}
    for r, _, _ in rows:
        by_lba.setdefault(r["lba"], []).append(r["seq"])
    pos = {k: 0 for k in by_lba}
    host = {}
    miss = 0
    for _, lat_ms, off in fio:
        lba = off // 4096
        lst = by_lba.get(lba)
        if lst is None or pos[lba] >= len(lst):
            miss += 1
            continue
        host[lst[pos[lba]]] = lat_ms
        pos[lba] += 1
    return host, miss


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, int(round(p / 100.0 * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    path = args[0]
    csv_path = args[args.index("--csv") + 1] if "--csv" in args else None
    stall_ms = float(args[args.index("--stall-ms") + 1]) if "--stall-ms" in args else 1000.0
    nand_ms = float(args[args.index("--nand-ms") + 1]) if "--nand-ms" in args else 0.3
    die_ms = float(args[args.index("--die-ms") + 1]) if "--die-ms" in args else 0.57
    fio_paths = [args[i + 1] for i, a in enumerate(args) if a == "--fio-log"]

    h, recs = load(path)
    unit_ms = (1 << h["timeShift"]) * 1000.0 / h["countsPerSecond"]
    print("header: " + ", ".join("%s=%d" % (k, h[k]) for k in HDR_NAMES if k not in ("magic", "recBytes", "recOffset")))
    print("records parsed: %d, unit = %.6f ms" % (len(recs), unit_ms))
    if h["stopFlag"]:
        print("WARNING: log was full, %d records dropped" % h["dropped"])
    if not recs:
        return

    nand_ticks = int(nand_ms / unit_ms)
    rows = []
    adj = {}
    for r in recs:
        s = segments(r, None)                  # primary: team rule
        adj[r["seq"]] = segments(r, nand_ticks)   # secondary: polling-adjusted
        total = r["dDmaEnd"]
        rows.append((r, s, total))

    host = {}
    if fio_paths:
        fio = load_fio(fio_paths)
        host, miss = match_fio(rows, fio)
        print("fio reads: %d, matched to records: %d, unmatched: %d" % (len(fio), len(host), miss))

    if csv_path:
        with open(csv_path, "w") as f:
            f.write("seq,lba,flags,aheadCnt,schedTrig,schedXfer,total_ms,host_ms,fetchbefore_ms,buffer_ms,dieq_ms,loop_ms,xferwait_ms,nanddma_ms,loop_adj_ms,nanddma_adj_ms\n")
            for r, s, total in rows:
                hm = host.get(r["seq"])
                a = adj[r["seq"]]
                f.write("%d,%d,0x%04x,%d,%d,%d,%.4f,%s,%s,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n" % (
                    r["seq"], r["lba"], r["flags"], r["aheadCnt"], r["schedTrig"], r["schedXfer"], total * unit_ms,
                    "%.4f" % hm if hm is not None else "", "%.4f" % (hm - total * unit_ms) if hm is not None else "",
                    s["buffer"] * unit_ms, s["dieq"] * unit_ms, s["loop"] * unit_ms,
                    s["xferwait"] * unit_ms, s["nanddma"] * unit_ms, a["loop"] * unit_ms, a["nanddma"] * unit_ms))
        print("csv written: %s" % csv_path)

    totals = sorted(t * unit_ms for _, _, t in rows)
    print("firmware-internal read latency (tFetch..DMA end): p50=%.3f ms p99=%.3f ms p99.9=%.3f ms max=%.3f ms"
          % (pct(totals, 50), pct(totals, 99), pct(totals, 99.9), totals[-1]))
    print("flags: buf-hit=%d unmapped=%d rbuf-entry=%d saturated=%d"
          % (sum(1 for r, _, _ in rows if r["flags"] & 1), sum(1 for r, _, _ in rows if r["flags"] & 0x10),
             sum(1 for r, _, _ in rows if r["flags"] & 2), sum(1 for r, _, _ in rows if r["flags"] & 8)))

    # ---- sanity checks (compare with the expected values in docs/experiment-plan-2026-10-09.md section 3-5) ----
    order = ["dBufAlloc", "dEnqueue", "dIssue", "dTrigDone", "dXferIssue", "dNandDone", "dDmaStart", "dDmaEnd"]
    nand_recs = [r for r, _, _ in rows if not (r["flags"] & 0x11)]
    bad = [r for r in nand_recs if any(r[order[i]] > r[order[i + 1]] for i in range(len(order) - 1))]
    miss_recs = nand_recs
    print("sanity: records with NAND access=%d, time-order violations=%d (should be ~0)" % (len(nand_recs), len(bad)))
    if bad:
        print("  first violations (seq): %s" % ", ".join(str(r["seq"]) for r in bad[:5]))
    if miss_recs:
        print("sanity: R-Buf read-entry flag on %.1f%% of NAND reads (R-Buf build: ~100%%, S-Buf build: 0%%)" %
              (100.0 * sum(1 for r in miss_recs if r["flags"] & 2) / len(miss_recs)))
    print("sanity: buffer-hit reads %.2f%% (random 4KB reads over 8GB: expect well under 1%%)" %
          (100.0 * sum(1 for r, _, _ in rows if r["flags"] & 1) / len(rows)))
    if host:
        fbs = sorted((host[r["seq"]] - t * unit_ms) for r, _, t in rows if r["seq"] in host)
        neg = sum(1 for x in fbs if x < 0)
        print("sanity: fetch-before (host - firmware): median=%.3f ms, p99=%.3f ms, negative=%d of %d "
              "(negative or large median = matching error or clock/unit problem)" % (pct(fbs, 50), pct(fbs, 99), neg, len(fbs)))

    keys = ["buffer", "dieq", "loop", "xferwait", "nanddma"]

    def summarize(sel, title):
        if not sel:
            print("%s: none" % title)
            return
        tot = {k: sum(s[k] for _, s, _ in sel) * unit_ms for k in keys}
        grand = sum(tot.values()) or 1.0
        print("%s (%d reads): " % (title, len(sel)) + ", ".join(
            "%s %.1f%% (%.1f ms)" % (k, 100.0 * tot[k] / grand, tot[k]) for k in keys))

    def view(sel, title):
        summarize(sel, title + " [team rule]")
        summarize([(r, adj[r["seq"]], t) for r, _, t in sel], title + " [polling-adjusted, secondary]")

    view(rows, "all reads")
    p99 = pct(totals, 99)
    view([x for x in rows if x[2] * unit_ms > p99], "slower than p99")
    if host:
        stalls = [x for x in rows if host.get(x[0]["seq"], x[2] * unit_ms) >= stall_ms]
        print("stalls selected by HOST latency >= %.0f ms (firmware-only selection would miss fetch-before waits)" % stall_ms)
    else:
        stalls = [x for x in rows if x[2] * unit_ms >= stall_ms]
    view(stalls, "stalls >= %.0f ms" % stall_ms)

    print("\nstall list (seq, host ms, firmware ms, fetch-before ms, dominant segment, per-segment ms, calls):")
    for r, s, total in stalls:
        dom = max(keys, key=lambda k: s[k])
        dom_adj = max(keys, key=lambda k: adj[r["seq"]][k])
        fw = total * unit_ms
        hm = host.get(r["seq"])
        fb = (hm - fw) if hm is not None else None
        if fb is not None and fb > fw and fb > stall_ms * 0.5:
            dom = "fetch-before (N2)"
        sus = ""
        if not (r["flags"] & 0x11) and s["dieq"] * unit_ms > 3 * (r["aheadCnt"] + 1) * die_ms:
            sus = " dieq-suspect(polling?)"
        print("  seq %d  host=%s  fw=%.1f ms  fetch-before=%s  -> %s (polling-adjusted: %s)  [%s]  ahead=%d  calls trig=%d xfer=%d  flags=0x%04x%s" % (
            r["seq"], ("%.1f ms" % hm) if hm is not None else "n/a", fw,
            ("%.1f ms" % fb) if fb is not None else "n/a", dom, dom_adj,
            " ".join("%s=%.1f" % (k, s[k] * unit_ms) for k in keys),
            r["aheadCnt"], r["schedTrig"], r["schedXfer"], r["flags"], sus))


if __name__ == "__main__":
    main()
