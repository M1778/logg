# logg

Structured logging for [Fin](https://github.com/M1778/Fin). Zero dependencies.

Levels, key=value structured fields, console + file outputs, optional
JSON-lines format, and level filtering through a per-logger threshold.

> Tested with finc 0.4.0 (contract 3) on Linux at `-O0` and `-O2`.
> Tests parse JSON, check single-line escaping, reject metadata collisions,
> capture fatal output, exercise write/close/flush failures, and measure the
> filtered hot path and large-record throughput. See **Testing** below.

## Install

Requires the `finn` package manager (https://github.com/M1778/finn):

```sh
finn add M1778/logg
```

## Quick Example

```fin
import { Logger, logg_new, logg_set_level, logg_set_json, logg_set_file,
         logg_info, logg_fields } from logg::fin;
import { Collection } from collection::std;

fun main() <noret> {
    let log <Logger> = logg_new("myapp");
    logg_info(&log, "server starting");

    let keys <&Collection<string>> = new Collection::<string>{};
    let vals <&Collection<string>> = new Collection::<string>{};
    keys.push("port");
    vals.push("8080");
    logg_fields(&log, 1, "listening", keys, vals);  // INFO + fields

    let jl <Logger> = logg_new("myapp");            // JSON to a file
    logg_set_json(&jl, true);
    logg_set_file(&jl, "app.log");
    logg_info(&jl, "structured line in app.log");
}
```

Output (text):

```
2026-10-20T09:41:00Z INFO [myapp] server starting
2026-10-20T09:41:00Z INFO [myapp] listening port=8080
```

Output (JSON lines):

```json
{"ts":"2026-10-20T09:41:00Z","level":"INFO","logger":"myapp","msg":"structured line in app.log"}
```

> Import spelling: `logg::fin` means module `logg` (the file
> `src/logg.fin`), namespace `fin`. Import the names you need **by name** —
> qualified calls (`logg.logg_info(...)`) are refused by the backend; see
> `docs/guide/10-modules-and-imports.md` in the Fin repo.

## Design notes

- **Filtering:** messages below the threshold return before allocating,
  formatting, reading the clock, or touching I/O. Plain messages use stack-local
  empty Collections; they do not allocate field containers. Argument expressions
  are still evaluated by the caller before the logging function runs.
- **Levels** are plain ints: 0=DEBUG, 1=INFO, 2=WARN, 3=ERROR, 4=FATAL.
  `logg_level_name()` returns their readable names.
- **FATAL:** existing emit functions write and then abort via `blame`. The new
  `logg_try_*` functions return a status even at FATAL; they never abort or print
  their own diagnostics.
- **Ownership:** logger names, paths, field Collections, and field strings remain
  caller-owned. The logger frees every formatting buffer, including byte arrays.
  Strings returned by `logg_level_name` and `logg_status_name` are literals; do not
  free them. The current stdlib Collection has no public backing-buffer release
  method; reuse caller-owned Collections rather than allocating them per record.
- **Single-line output:** names, messages, keys, and values escape quotes,
  backslashes, ASCII controls (including DEL), UTF-8 C1 controls, and Unicode
  line/paragraph separators. Text field keys and values are quoted when needed.
  JSON keeps ordinary fields at the top level. Input is NUL-terminated UTF-8;
  embedded NUL terminates a string, and malformed UTF-8 is not repaired.
- **Protected metadata:** both formats reject an entire record if a field key is
  `ts`, `level`, `logger`, or `msg`, or if two keys have identical bytes. Null keys
  are rejected too. Empty keys are allowed. These failures cause no output I/O.
- **Checked output:** files use open-append-write-close with both write and close
  results checked. Console output flushes C output streams before a checked,
  unbuffered stdout write, retrying interrupted and partial writes. This preserves
  buffered `printf` ordering and fatal output when stdout is redirected. A flush
  failure still returns an error even if the record itself was written.
  A successful status is not an `fsync` durability guarantee. A failed write may
  leave a partial record; concurrent multi-process records are not guaranteed
  atomic. POSIX SIGPIPE policy remains the application's responsibility: writing
  a closed pipe can terminate the process unless the application handles/ignores
  SIGPIPE. The library never changes signal handlers.

## API Reference

### Lifecycle

| Function | Description |
|---|---|
| `logg_new(name: string) <Logger>` | INFO threshold, text format, stdout. |
| `logg_set_level(&l, level: int)` | Threshold 0–4 (blames outside the range). |
| `logg_level(&l) <int>` | Current threshold. |
| `logg_set_json(&l, on: bool)` | JSON-lines vs human-readable text. |
| `logg_set_file(&l, path: string)` | Append to file; `""` restores stdout. |
| `logg_level_name(level: int) <string>` | `"DEBUG"`…`"FATAL"` (literal, do not free). |

### Emitting

| Function | Description |
|---|---|
| `logg_emit(&l, level, msg)` | Plain message at a level. |
| `logg_debug/info/warn/error(&l, msg)` | Shorthands. |
| `logg_fatal(&l, msg)` | Emits, then aborts via blame. |
| `logg_fields(&l, level, msg, &keys, &vals)` | Structured fields; mismatched lengths blame. Rejected keys/output failures report to stderr. |
| `logg_try_emit(&l, level, msg) <int>` | Plain message; returns status, never aborts. |
| `logg_try_fields(&l, level, msg, &keys, &vals) <int>` | Structured message; returns status, never aborts. |
| `logg_status_name(status: int) <string>` | Human-readable status literal. |

### Status results

| Code | Meaning |
|---|---|
| 0 | Record written. |
| 1 | Filtered; no allocation or I/O. |
| 2 | Invalid level (not 0–4). |
| 3 | Keys/values length mismatch. |
| 4 | Reserved, duplicate, or null key. |
| 5 | Output open/write/close/flush failure, or null file path. |
| 6 | Formatted record cannot fit a Fin int-sized buffer. |

The status APIs validate the level, then filter, then validate fields. A filtered
structured record therefore returns 1 without inspecting its keys or values.
Legacy wrappers retain their level/count assertions even when filtered, report
other failures as a fixed `logg: ...` line on stderr, and still abort at FATAL.
The logger does not take ownership of inputs, including on rejection. Allocation
failure follows the Fin/stdlib runtime policy; status 6 is a size guard, not a
recoverable out-of-memory guarantee. Duplicate checking is quadratic in field
count; formatting is linear in record bytes, with no per-byte allocations.

## Testing

The standalone Fin suite remains runnable:

```sh
finc -I src tests/test_logg.fin -o test_logg
./test_logg
```

The full regression runner supports native Linux, macOS, and Windows Python 3.
It compiles tests and the example at both optimization levels, uses isolated
temporary directories (`.exe` binaries on Windows), parses JSON with rejection
of duplicate keys, and removes generated binaries/logs afterwards:

```sh
python3 -I tests/run_tests.py --finc /path/to/finc --fin-libs /path/to/lib/std
```

On Windows, use a Developer PowerShell with `clang` available and `FIN_CC=clang`,
then run `python -I tests/run_tests.py --finc C:\path\finc.exe --fin-libs C:\path\lib\std`.
Standalone Windows builds likewise need `-o test_logg.exe` and `.\test_logg.exe`.

Golden/file-error/metadata/JSON tests and captured fatal assertions run on every
platform. Fatal tests require both the blame diagnostic and the platform's abort
status; the Windows test executable suppresses interactive CRT abort reporting.
Windows console assertions allow CRT CRLF translation without weakening the
byte-exact LF checks for binary log files. The library does not change stdout's
CRT mode; byte-oriented text/binary stdout is supported, not wide-character modes.
Linux additionally uses `/dev/full` and a C-compiler-built `LD_PRELOAD` shim to
inject partial-write, EINTR, and flush failures; neither mechanism runs elsewhere.

The runner benchmarks one million filtered calls plus 2,000 JSON records at 16
and 32 KiB (`NUL` on Windows, `/dev/null` otherwise). Per-child peak memory uses
POSIX `wait4` or Windows `GetProcessMemoryInfo`; growth over an empty-process
baseline must stay below 12 MiB. Wall times and scaling are reported rather than
asserted to avoid timing-sensitive failures.

Native Windows x86-64/ARM64, macOS ARM64 and both Linux architectures passed
the O0/O2 logging runner in [native run 40034272733](https://github.com/M1778/fin-sdk/actions/runs/40034272733),
at logg revision `12b5550c2173bbe948e6385a8b49c8db4129112e`. The run used
externally verified compiler candidate `5360b051b8e82a4f10052c3dbb77bc66cc727cd7`
from CI run `40028977601`, not a compiler release. These are per-project results;
unrelated projects may still fail the overall run. Published Fin `1f7afd97`
lacks target selectors and cannot select Windows/macOS bindings correctly.
Linux-only failure injection is not claimed as Windows/macOS coverage.

## Dependencies

None beyond the Fin standard library (`collection`, `strings`, `time`) and
platform libc I/O/memory functions. No third-party runtime packages or extra
link flags.

## License

MIT
