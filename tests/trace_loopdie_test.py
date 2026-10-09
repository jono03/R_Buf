"""Synthetic test of tools/trace_loopdie.py: die-busy case (many scheduler passes) vs loop-starved case (few passes)."""
import os, struct, subprocess, sys, tempfile
TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, TOOLS)
import trace_parse as t
CPS, SHIFT = 500000000, 6
unit = (1 << SHIFT) * 1000.0 / CPS
def ticks(ms): return int(round(ms / unit))
def rec(seq, lba, fetch_ms, enq_ms, issue_ms, ahead, passes):
    # fields: seq lba tFetch dBufAlloc dEnqueue dDieLastDone dIssue dNandDone dDmaStart dDmaEnd flags ahead dXferIssue dTrigDone sTrig sXfer sXferWait sDieQ
    return struct.pack(t.REC_FMT, seq, lba, int(fetch_ms * CPS / 1000.0), 0, ticks(enq_ms), ticks(issue_ms), ticks(issue_ms), ticks(issue_ms + 0.2),
                       ticks(issue_ms + 0.2), ticks(issue_ms + 0.3), 2, ahead, 0, 0, 0, 0, 0, passes)
recs, seq, now = [], 0, 0.0
recs.append(rec(seq, 1, now, 0.0, 0.1, 0, 5)); seq += 1; now += 1.0         # first mapped read starts 'ro'
now += 10000.0                                                                   # > ro window of 1 s below
for i in range(20):   # die busy: 3 ms window, 2 requests ahead, 300 passes -> interval 10 us, loop estimate 3*10us=30us (1%)
    recs.append(rec(seq, 100 + i, now, 0.0, 3.0, 2, 300)); seq += 1; now += 5.0
for i in range(20):   # loop starved: 3 ms window, 2 requests ahead, 1 pass -> interval 1.5 ms, loop estimate = min(3, 3*1.5)=3 ms (100%)
    recs.append(rec(seq, 200 + i, now, 0.0, 3.0, 2, 1)); seq += 1; now += 5.0
hdr = struct.pack(t.HDR_FMT, t.MAGIC, 3, len(recs), 0, 1, 1, 0, 8, CPS, SHIFT, 8, 64, 0x1000, 0, 0, 0, 0, 0, 0)
d = tempfile.mkdtemp()
open(os.path.join(d, "x.bin"), "wb").write(hdr + b"\0" * (0x1000 - len(hdr)) + b"".join(recs))
out = subprocess.run([sys.executable, os.path.join(TOOLS, "trace_loopdie.py"), os.path.join(d, "x.bin"), "--ro-s", "1"], capture_output=True, text=True)
print(out.stdout, out.stderr)
assert "storm NAND reads=40" in out.stdout, out.stdout
assert "reads with interval > 0.1 ms: 20, > 1 ms: 20" in out.stdout, out.stdout
assert "loop estimate 50.5%" in out.stdout, out.stdout
print("TRACE_LOOPDIE TEST OK")
