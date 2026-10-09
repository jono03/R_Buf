"""Synthetic test of tools/trace_where.py: one stall before the firmware fetch, one after the firmware DMA end."""
import os, struct, subprocess, sys, tempfile
TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, TOOLS)
import trace_parse as t

CPS = 500000000
SHIFT = 6
unit = (1 << SHIFT) * 1000.0 / CPS            # ms per tick
OFFSET = -12345.678                           # fw clock = fio clock + OFFSET (fio time = fw time + 12345.678)

def rec(seq, lba, fetch_ms, fw_ms):
    tk = int(round(fw_ms / unit))
    return struct.pack(t.REC_FMT, seq, lba, int(fetch_ms * CPS / 1000.0), 0, 0, 0, 0, 0, 0, tk, 2, 0, 0, 0, 0, 0, 0, 0)

recs, log = [], []
for i in range(300):
    sub = 100.0 + i * 2.0                      # fw clock ms
    recs.append(rec(i, 1000 + i, sub + 0.01, 0.2))
    done = sub + 0.01 + 0.2 + 0.02
    log.append(done)
# stall A: command sits 3000 ms before the firmware fetches it
subA = 800.0
recs.append(rec(300, 5000, subA + 3000.0, 0.3))
doneA = subA + 3000.0 + 0.3 + 0.02
# stall B: firmware is quick, the completion reaches the host 4000 ms later
subB = 900.0
recs.append(rec(301, 5001, subB + 0.01, 0.3))
doneB = subB + 0.01 + 0.3 + 4000.0

entries = [(done, 0.23, 1000 + i) for i, done in enumerate(log)]
entries.append((doneA, doneA - subA, 5000))
entries.append((doneB, doneB - subB, 5001))
hdr = struct.pack(t.HDR_FMT, t.MAGIC, 3, len(recs), 0, 1, 1, 0, 8, CPS, SHIFT, 8, 64, 0x1000, 0, 0, 0, 0, 0, 0)
d = tempfile.mkdtemp()
with open(os.path.join(d, "x.bin"), "wb") as f:
    f.write(hdr + b"\0" * (0x1000 - len(hdr)) + b"".join(recs))
with open(os.path.join(d, "x.log"), "w") as f:
    for done, lat, lba in entries:
        f.write("%d, %d, 0, 4096, %d, 0\n" % (round(done - OFFSET), round(lat * 1e6), lba * 4096))
out = subprocess.run([sys.executable, os.path.join(TOOLS, "trace_where.py"), os.path.join(d, "x.bin"),
                      "--fio-log", os.path.join(d, "x.log"), "--stall-ms", "1000"], capture_output=True, text=True)
print(out.stdout, out.stderr)
assert "before-fetch" in out.stdout and "after-DMA" in out.stdout, "expected both classes"
assert "before-fetch 1, after-DMA 1" in out.stdout
print("TRACE_WHERE TEST OK")
