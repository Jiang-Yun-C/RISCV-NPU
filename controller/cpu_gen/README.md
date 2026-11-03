> Demo V6: the selected `t27/cpu/T09Cpu.v` now uses patch 003 for precise store responses and the machine-state fixes. The old `generated/` tree below remains historical. See `../docs/spec/machine-irq-v6.md` for the new contract.

# Reproducible T09 cache and prediction variants

This directory restores a complete, rebuildable generator for the exported T09 configuration. It starts from the pinned public VexRiscv archive, applies two readable patches, and elaborates SpinalHDL 1.13.0 / Scala 2.12.18 using sbt 1.6.0 and Java 17. The original `t27/cpu/T09Cpu.v` remains the historical reference until an explicit hardware profile is staged.

## Provenance and limits

The historical export contained generated RTL but omitted the complete Scala generator. `evidence/GenT09_historical_excerpt.txt` was recovered from the existing source excerpt archive. Imports and a complete build wrapper were reconstructed; this is **not** a claim that the complete original Scala file was recovered byte for byte.

`evidence/GenT09_reconstructed_baseline.scala.txt` together with patch 001 generates a baseline whose text is identical to the historical RTL after a bijective renaming of 13 source-line-derived identifiers. `evidence/BASELINE_RECONSTRUCTION.json` records both hashes and the exact mapping. Actual CPU execution additionally checks byte writes, cache invalidation, self-modifying code, branches, indirect calls, and both short CoreMark seeds. Neither the text comparison nor those workloads replaces a complete formal CPU proof.

Upstream source: https://github.com/SpinalHDL/VexRiscv/tree/baf7dc82f855eddaf5b0a20a6802c526f127e38a . The exact archive is included under `upstream/`; its SHA-256 is checked before extraction. Its MIT license is retained in the archive and copied beside it. SpinalHDL is resolved as published Maven artifacts, version 1.13.0. Its generated header reports git head `d9d72474863badf47d8585d187f3e04ae4749c59`, matching the original export.

## What changes

Patch 001 reconstructs the historical startup clearing of the direction predictor and the original refill-triggered cache allocation behavior. Patch 002 adds selectable cache policies and safe startup clearing of the upstream fetch-target predictor. The application, ISA, address map, cache line size and external CPU interface are preserved for the tested 16 KiB configuration.

| Variant | I/D replacement | Predictor |
| --- | --- | --- |
| `global` | Historical shared rotation | Decode direction prediction |
| `rr` | Empty way first, then per-set rotation | Decode direction prediction |
| `lru` | Empty way first, then two-way per-set LRU | Decode direction prediction |
| `btb` | Historical shared rotation | Fetch-stage target prediction |
| `lru_btb` | Empty way first, then two-way per-set LRU | Fetch-stage target prediction |

Both per-set policies use one replacement bit per set per cache. A refill latches its chosen way; accepted hits update the LRU bit only for the LRU configuration. Flush/reset tag sweeps also reset replacement state. BTB startup clears the actual prediction RAM write port after the upstream address mapping and holds fetch until the sweep completes. The existing read-only trace interface is preserved.

## Generate

From the `source/` directory:

```sh
python3 scripts/build_cpu_variants.py --output /absolute/new/cpu-build --variant all
```

If sbt is not on PATH, use a locally installed sbt 1.6.0 launcher:

```sh
python3 scripts/build_cpu_variants.py --output /absolute/new/cpu-build \
  --variant all --sbt-launcher /absolute/sbt-launch-1.6.0.jar \
  --dependency-cache /absolute/task-specific-sbt-cache
```

The launcher SHA-256 used for this deliverable is `627ddd9b3524369edaf891577a0c59e8bf70e783f751c12f4be779663ad29844`. Its official public artifact is https://repo.maven.apache.org/maven2/org/scala-sbt/sbt-launch/1.6.0/sbt-launch-1.6.0.jar . The generator never writes into the historical CPU directory. Use a new output directory outside `cpu_gen/` whose path has no whitespace; unsupported paths are rejected before writing. It records input/output hashes, complete command, stdout and tool versions. The first build requires public Maven dependencies if they are not already cached.

Default: RV32IMF, five stages, 16 KiB I-cache and 16 KiB D-cache, two ways, 32-byte lines, predictor history log2=8. The 8/32 KiB and history-size options are generation experiments; the delivered execution evidence is for the default sizes only. CPU variants require a fresh synthesis, placement, timing and resource check before board use. No new Fmax, LUT count or formal CoreMark/MHz is inferred from RTL simulation.

## Execute a generated CPU

`tests/cpu_variants/run.py` compiles five directed RV32 workloads, builds an actual Verilator CPU simulator and records RTL, firmware, initialization and harness identities. It also accepts the existing CoreMark binaries. It checks result/CRC contents in addition to CPU completion. See `tests/cpu_variants/README.md` and the top-level `verification/v3/cpu/` evidence for commands and scopes. These simulations use bounded behavioral external memory; a separate production-SRAM harness measures the real local memory controller.
