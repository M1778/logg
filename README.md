# logg

Structured logging for [Fin](https://github.com/M1778/Fin): levels, key/value
fields, a level threshold, console or append-to-file output, and an optional
JSON-lines format.

Verified against **finc 1.0.0 / 1.0.1 (contract 3)**. Tests compile and execute;
they do not merely type-check.

## What it does

- Five levels as plain ints: `0` DEBUG, `1` INFO, `2` WARN, `3` ERROR, `4` FATAL.
- A per-logger threshold. A record below it returns before allocating,
  formatting, reading the clock, or touching the output.
- Text records (`<ts> LEVEL [logger] message key=value`) and JSON-lines records
  (`{"ts":...,"level":...,"logger":...,"msg":...,...}`).
- Structured fields from two `Collection<string>` of equal length.
- Console (stdout) or append-to-file output, with write/close/flush results
  checked.
- Two API styles: emitting functions that abort on FATAL, and `logg_try_*`
  functions that return a status and never abort.

## What it does not do

- **No log rotation, no async or background flushing, no colour, no second
  output format, no filtering by logger name, no sampling.** Out of scope.
- **No cross-process atomicity.** One record is one `write()` call, so records
  from threads and processes that share a file do not interleave. A crash or a
  failed write can still leave a partial record. `status 0` is not fsync
  durability.
- **No wide-character console support.** Output is byte-oriented UTF-8; it does
  not call `_setmode`.
- **No SIGPIPE policy change.** Writing a closed pipe can kill the process
  unless the application handles SIGPIPE. The library never touches signal
  handlers.
- **No recoverable allocation failure.** Status `6` is a size guard, not an
  out-of-memory guarantee; allocation failure follows the Fin runtime.
- **No input ownership.** Logger names, paths, field collections and field
  strings stay caller-owned and are never freed by the logger.

## Install

Requires the `finn` package manager and a `finc` that speaks contract 3.

```sh
finn add M1778/logg
```

Then import the library by module, resolving `src/` with `-I`:

```fin fragment
import { Logger, logg_new, logg_info } from logg::fin;
```

## Complete runnable example

```fin
import { Logger, logg_new, logg_set_level, logg_set_json, logg_set_file,
         logg_info, logg_warn, logg_error, logg_fields } from logg::fin;
import { Collection } from collection::std;

fun main() <noret> {
    // Console logger, INFO and above, human-readable text.
    let log <Logger> = logg_new("example");
    logg_info(&log, "server starting");

    let keys <&Collection<string>> = new Collection::<string>{};
    let vals <&Collection<string>> = new Collection::<string>{};
    keys.push("port");
    vals.push("8080");
    keys.push("mode");
    vals.push("debug build");
    logg_fields(&log, 1, "listening", keys, vals);

    // File logger, DEBUG and above, JSON lines.
    let jl <Logger> = logg_new("example");
    logg_set_level(&jl, 0);
    logg_set_json(&jl, true);
    logg_set_file(&jl, "example.log");
    logg_info(&jl, "json line written to example.log");
    logg_warn(&jl, "something looks off");

    logg_error(&log, "shutting down");
    printf("wrote example.log\n");
}
```

```sh
finc -I src examples/basic.fin -o basic && ./basic
```

```output
2026-11-21T00:45:36Z INFO [example] server starting
2026-11-21T00:45:36Z INFO [example] listening port=8080 mode="debug build"
2026-11-21T00:45:36Z ERROR [example] shutting down
wrote example.log
```

`example.log` holds the two JSON records, one per line.

## Public API

Every name below is exported from `src/logg.fin` (module `logg`, namespace `fin`).

### Lifecycle

| Function | Description |
|---|---|
| `logg_new(name: string) <Logger>` | INFO threshold, text format, stdout. `name` is caller-owned. |
| `logg_set_level(&l, level: int)` | Threshold `0..4`. Blames outside that range. |
| `logg_level(&l) <int>` | Current threshold. |
| `logg_set_json(&l, on: bool)` | JSON lines instead of text. |
| `logg_set_file(&l, path: string)` | Append to `path`; `""` restores stdout. |
| `logg_level_name(level: int) <string>` | `"DEBUG"`…`"FATAL"`; a literal, do not free. |
| `logg_status_name(status: int) <string>` | Human-readable status; a literal, do not free. |

### Emitting

| Function | Description |
|---|---|
| `logg_emit(&l, level, msg)` | Plain record. Blames on an invalid level. |
| `logg_debug/info/warn/error(&l, msg)` | Level shorthands. |
| `logg_fatal(&l, msg)` | Writes, then aborts via `blame`. |
| `logg_fields(&l, level, msg, &keys, &vals)` | Structured record. Blames on mismatched lengths; reports rejection and I/O failures as a fixed line on stderr. |
| `logg_try_emit(&l, level, msg) <int>` | Plain record; returns a status, never aborts. |
| `logg_try_fields(&l, level, msg, &keys, &vals) <int>` | Structured record; returns a status, never aborts. |

### Status results

| Code | Meaning |
|---|---|
| 0 | Record written. |
| 1 | Filtered by the threshold; no allocation or I/O. |
| 2 | Invalid level (not `0..4`). |
| 3 | Keys/values length mismatch. |
| 4 | Reserved, duplicate, or null key. |
| 5 | Output open/write/close/flush failure, or null file path. |
| 6 | Record cannot fit a Fin int-sized buffer. |

`logg_try_*` validates the level first, then filters, then validates fields, so a
filtered structured record returns `1` without inspecting its keys or values.

## Behavior worth knowing

**Escaping.** Names, messages, keys and values escape `"`, `\`, ASCII controls
including DEL, UTF-8 C1 controls, and U+2028/U+2029. A record always ends in
exactly one `\n` and carries no raw control byte, so a message containing a
newline cannot become two records. Input that is not well-formed UTF-8 (a lone
continuation byte, an overlong form, a surrogate, a truncated sequence) is
escaped byte by byte rather than passed through, so the emitted line is always
valid JSON and always well-formed UTF-8. Input is NUL-terminated; a string ends
at its first NUL byte.

**Protected metadata.** Both formats reject an entire record if a field key is
`ts`, `level`, `logger` or `msg`, if two keys are byte-identical, or if a key is
null. A rejected record performs no output I/O. Empty keys are allowed.

**Concurrency.** Each record opens the file, writes it with one descriptor write,
and closes it. Nothing goes through stdio's buffer, so a record is never split,
and POSIX `O_APPEND` / Windows `FILE_APPEND_DATA` make the write land at the
current end of the file. Records from concurrent threads or processes therefore
do not interleave. The suite asserts this with four writers, 16 KiB records, and
an exact record count, on all three platforms. `setvbuf` is deliberately not
used: reconfiguring a stdio stream from a worker thread fails on the Windows CRT.

**Threshold.** `level < threshold` is dropped, so a WARN threshold keeps WARN,
ERROR and FATAL and drops DEBUG and INFO.

## Platform support

| Platform | Status |
|---|---|
| Linux (x86_64, glibc) | Compiled and executed in CI and locally. `/dev/full` and an `LD_PRELOAD` shim inject the write/flush failure modes. |
| macOS (arm64, `macos-14`) | Compiled and executed in CI. No `/dev/full`, so that one lane is skipped and reported. |
| Windows (x86_64, `windows-2022`) | Compiled and executed in CI. Uses `_errno`, `_write` and `__acrt_iob_func`; the file path uses the C runtime's `fopen`/`fwrite`. |

The POSIX calls (`write`, `dprintf`, `__errno_location`) are compiled only for
non-Windows targets; Windows uses the CRT equivalents. The library relies on
libc and the Fin standard library (`collection`, `strings`, `time`), with no
third-party runtime or extra link flags.

## Testing

```sh
python3 -I tests/run_tests.py --finc /path/to/finc
```

The runner compiles at `-O0` and `-O2` and executes both binaries. It:

- parses every emitted record with Python's JSON parser, rejecting duplicate
  keys, and checks each text record is a single line with no raw control bytes;
- drives control-character, malformed UTF-8 and metadata-collision records;
- asserts the threshold boundary (WARN keeps WARN, drops INFO and DEBUG);
- checks the write, close, flush, open-error and partial/interrupted-write paths,
  using `/dev/full` and a C `LD_PRELOAD` shim on Linux;
- runs four threads writing 64 KiB records to one file and asserts no record is
  split;
- verifies one record larger than stdio's buffer reaches the kernel as one write;
- runs the example and parses its output file.

`finc -I src tests/test_logg.fin -o test_logg && ./test_logg` also runs
standalone. On Windows use `-o test_logg.exe` and `.\test_logg.exe`.

## License

MIT. See [LICENSE](LICENSE).
