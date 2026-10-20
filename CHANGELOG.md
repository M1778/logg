# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.0] - 2026-10-20

### Added
- Initial release: structured logging for Fin, zero dependencies.
- Levels 0–4 (DEBUG/INFO/WARN/ERROR/FATAL) as documented int codes (no
  `const` — finc 0.4.0 does not lower consts from imported modules).
- `Logger` struct with per-logger threshold filtering (no mutable module
  globals exist in Fin 0.4.0); below-threshold messages return before any
  formatting or I/O.
- Console + file outputs (`""` = stdout, else append per line), human text
  format and JSON-lines format (proper `\"`/`\\`/control-char escaping).
- Structured fields via `logg_fields` (`&Collection<string>` key/val pairs):
  `k=v` in text (values with spaces/quotes/`=` auto-quoted), `"k":"v"` in
  JSON; length mismatch is a blame error.
- `logg_fatal` emits then aborts via blame, mirroring `testing::std`.
- RFC3339 timestamps via `time::std` (allocated strings freed internally).
- Tests (`tests/test_logg.fin`): level names, threshold filtering (file
  readback), text fields + quoting, JSON format + escaping, emit shorthands,
  console smoke — all against `testing::std` asserts, zero test deps.
- Example (`examples/basic.fin`), GitHub Actions CI (builds finc from source,
  type-checks, runs tests, runs example, verifies `example.log`), `finn.toml`,
  MIT license.

### Verification
- VERIFIED 2026-10-20: compiled with finc 0.4.0 (day-1 sandbox build;
  `libllvm22` installed via apt.llvm.org for the `libLLVM.so.22.1` link).
  Tests pass with exit 0: level names, threshold filtering (below-threshold
  messages dropped before formatting — verified via file readback), text
  fields with auto-quoting of spaced values, JSON-lines format with proper
  `\"` escaping, all emit shorthands, console smoke test. Example runs and
  produces valid JSON lines in `example.log`.
