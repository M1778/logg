# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed

- **Concurrent records could interleave in a log file.** Every record was written
  through a buffered `FILE *`, so a record larger than stdio's 64 KiB buffer was
  split across several `write()` calls and a second thread could land inside it.
  Two threads appending 64 KiB records produced unparseable lines roughly nine
  runs in ten. File output now writes each record with a single descriptor
  write, never through stdio's buffer, and relies on `O_APPEND` (POSIX) or
  `FILE_APPEND_DATA` (Windows) to place it at the current end of the file. The
  test suite writes from four threads and asserts every line is exactly one
  intact record, on all three platforms.
- **A message that was not well-formed UTF-8 produced a line no JSON parser
  accepts.** A lone continuation byte, an overlong form, a UTF-16 surrogate or a
  truncated sequence was passed through unchanged, so the record was not valid
  JSON or even valid UTF-8. Escaping now validates each sequence and escapes any
  byte that does not start one, preserving its value instead of dropping it.
  Two-byte sequences above U+007F were also decoded with the wrong base, which
  mis-escaped ordinary text such as `é`.

### Changed

- Escaping is now decided per Unicode code point rather than per byte, so
  well-formed multi-byte characters pass through whole and are never truncated.
- README rewritten to state what the library does and does not do, the exact
  `finc` version it was verified against, and the per-platform status.
- `exports.fin` documents that Fin has no `export` keyword, so the file is a
  `finn` package-layout placeholder and must not be compiled.
- CI installs a pinned `finc` release, verifies its published sha256, and runs
  the full test suite on Linux, macOS and Windows.

### Added

- Every source file carries the project header (`scripts/fin_header.py`).
- `FINC_VERSION` pins the compiler used by CI in one visible place.
- `ci/install_finc.py` installs that pinned release, refuses a hash mismatch, and
  falls back to a source build when the runner has no published artifact.
- Regression tests for malformed-UTF-8 escaping and concurrent file records.
- A C shim mode that refuses a buffered large write, making the one-write-per-
  record guarantee a deterministic assertion on Linux.
- Windows CI now actually runs: the shared installer no longer prints the
  disabled `::add-path::` command, and the macOS lane installs the LLVM keg its
  published `finc` links against.

### Verification

- VERIFIED 2026-11-21 with finc 1.0.1 (contract 3) on Linux x86_64, at `-O0` and
  `-O2`: `tests/run_tests.py` passes, including strict JSON parsing of every
  record, malformed-UTF-8 escaping, four-thread file appends, and the
  write/close/flush failure modes.

## [0.1.0] - 2026-10-20

### Added
- Initial release: structured logging for Fin, zero dependencies.
- Levels 0–4 (DEBUG/INFO/WARN/ERROR/FATAL) as documented int codes.
- `Logger` struct with per-logger threshold filtering; below-threshold messages
  return before any formatting or I/O.
- Console + file outputs (`""` = stdout, else append per line), human text
  format and JSON-lines format.
- Structured fields via `logg_fields` (`&Collection<string>` key/val pairs).
- `logg_fatal` emits then aborts via blame.
- RFC3339 timestamps via `time::std`.
- Tests, example, GitHub Actions CI, `finn.toml`, MIT license.
