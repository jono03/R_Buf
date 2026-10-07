# R_Buf

Cosmos+ OpenSSD GreedyFTL v3.0.0 with a minimal re-implementation of R-Buf
(read buffer separated from write buffer, "Your Read is Our Priority in Flash Storage", VLDB 2022).

- `source/software/GreedyFTL-3.0.0/` – firmware. First commit is the unmodified upstream code.
- `ftl_config.h`: `RBUF_ENABLE` (0 = original, 1 = R-Buf; override with `-DRBUF_ENABLE=1`). Default 0.
- R-Buf read buffer = `1 x USER_DIES` entries carved out of the existing buffer array (same total size).
- `tests/rbuf_host/run.sh` – host-only logic test (no board needed).

Modified files carry a revision-history line. Licensed GPLv3 (see `LICENSE`), same as upstream.
