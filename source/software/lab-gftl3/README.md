# lab-gftl3: lab firmware base (unmodified)

Exact copy of `run-gftl3/src` from the lab SDK workspace (2026-10-07), before any R-Buf change.
Build outputs (`Debug/`, `Release/`, `.elf`, `.o`) are intentionally not included.

- Build flags seen in the SDK Debug config: `arm-none-eabi-gcc -O0 -g3`, no `-DNDEBUG` (so `assert()` is active).
- Lab-only files vs. the public GreedyFTL-3.0.0 tree: `t4nsc_pm.h`, `t4nsc_ucode.h` (NAND controller microcode). **Not committed here** (kept out until the team confirms the repo may hold them); copy them from the lab SDK `run-gftl3/src` to build.
- Differs from public base in: `ftl_config.{c,h}`, `nsc_driver.{c,h}`, `request_schedule.{c,h}`, `address_translation.c`, `data_buffer.{c,h}`, `request_transform.c`, `nvme/{host_lld,nvme_admin_cmd,nvme_io_cmd,nvme_main}.c`, `nvme/{host_lld,nvme}.h`.
- The R-Buf changes live in `../GreedyFTL-3.0.0/` (`data_buffer.c/h`, `request_transform.c`) and `board-config/ftl_config.h`; they are lab-base + R-Buf.
