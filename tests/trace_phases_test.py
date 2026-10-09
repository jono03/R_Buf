"""Synthetic test of tools/trace_phases.py: 5 unmapped boot reads | 36 s gap | ro reads (2 ms apart, 0.6 s) | 2 s gap | storm reads incl. a 30 s host stall gap."""
import os, struct, subprocess, sys, tempfile
TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, TOOLS)
import trace_parse as t
CPS, SHIFT = 500000000, 6
unit = (1 << SHIFT) * 1000.0 / CPS
def rec(seq, lba, fetch_ms, fw_ms):
    return struct.pack(t.REC_FMT, seq, lba, int(fetch_ms * CPS / 1000.0), 0, 0, 0, 0, 0, 0, int(round(fw_ms / unit)), 0, 0, 0, 0, 0, 0, 0, 0)
def rec2(seq, lba, fetch_ms, fw_ms, flags):
    return struct.pack(t.REC_FMT, seq, lba, int(fetch_ms * CPS / 1000.0), 0, 0, 0, 0, 0, 0, int(round(fw_ms / unit)), flags, 0, 0, 0, 0, 0, 0, 0)
recs, now, seq = [], 0.0, 0
for i in range(5):
    recs.append(rec2(seq, i, now, 0.1, 0x10)); seq += 1; now += 1.0
now += 36000.0
for i in range(300):                       # ro: 10 s window of 2 ms reads would be 5000 reads; use ro_s=1 below
    recs.append(rec2(seq, 100 + i, now, 0.2, 2)); seq += 1; now += 2.0
now += 2000.0
for i in range(50):
    recs.append(rec2(seq, 1000 + i, now, 5.0, 2)); seq += 1; now += 3.0
now += 30000.0                             # a host stall inside the storm: long gap between fetches
for i in range(50):
    recs.append(rec2(seq, 2000 + i, now, 5.0, 2)); seq += 1; now += 3.0
hdr = struct.pack(t.HDR_FMT, t.MAGIC, 3, len(recs), 0, 1, 1, 0, 8, CPS, SHIFT, 8, 64, 0x1000, 0, 0, 0, 0, 0, 0)
d = tempfile.mkdtemp()
open(os.path.join(d, "x.bin"), "wb").write(hdr + b"\0" * (0x1000 - len(hdr)) + b"".join(recs))
out = subprocess.run([sys.executable, os.path.join(TOOLS, "trace_phases.py"), os.path.join(d, "x.bin"), "--ro-s", "1"], capture_output=True, text=True)
print(out.stdout, out.stderr)
assert "boot  reads=5" in out.stdout and "ro    reads=300" in out.stdout and "storm reads=100" in out.stdout, out.stdout
print("TRACE_PHASES TEST OK")
