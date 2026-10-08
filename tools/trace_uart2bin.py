#!/usr/bin/env python3
"""Convert the UART text dump of the trace log (TRACE_UART_DUMP=1) into trace.bin.

usage: trace_uart2bin.py uart_log.txt trace.bin

Reads the lines "[TRC] H <19 hex words>" and "[TRC] R <idx> <16 hex words>" (other lines are ignored),
writes a 4KB header + the records in the order printed. When the firmware filtered records
(TRACE_UART_MIN_MS > 0) the header recCount is rewritten to the number of records actually present.
"""
import re
import struct
import sys

if len(sys.argv) != 3:
    sys.exit(__doc__)

hdr_words = None
recs = []
for line in open(sys.argv[1], errors="replace"):
    m = re.search(r"\[TRC\] H((?: [0-9a-fA-F]{8}){19})\s*$", line)
    if m:
        hdr_words = [int(x, 16) for x in m.group(1).split()]
        continue
    m = re.search(r"\[TRC\] R (\d+)((?: [0-9a-fA-F]{8}){16})\s*$", line)
    if m:
        recs.append([int(x, 16) for x in m.group(2).split()])

if hdr_words is None:
    sys.exit("no '[TRC] H' line found")
if hdr_words[2] != len(recs):
    print("note: header recCount=%d, records present=%d (filtered or incomplete UART capture)" % (hdr_words[2], len(recs)))
    hdr_words[2] = len(recs)

out = struct.pack("<19I", *hdr_words).ljust(0x1000, b"\0")
for r in recs:
    out += struct.pack("<16I", *r)
open(sys.argv[2], "wb").write(out)
print("wrote %s: %d records" % (sys.argv[2], len(recs)))
