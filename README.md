# logg

Structured logging for [Fin](https://github.com/M1778/Fin). Zero dependencies.

Levels, key=value structured fields, console + file outputs, optional
JSON-lines format, and level filtering through a per-logger threshold.

> **Verification status:** VERIFIED 2026-10-20 against finc 0.4.0 (built from
> source 2026-10-19; `libllvm22` installed via apt.llvm.org to satisfy the
> `libLLVM.so.22.1` link). Full test suite passes (exit 0): level names,
> threshold filtering (file readback), text fields + auto-quoting, JSON
> format + escaping, emit shorthands, console smoke. Example runs; log file
> output validated. Written against the Fin v0.4.0
> [agent guide](https://github.com/M1778/Fin/blob/master/docs/agent-guide.md)
> and the 8 measured finc backend limits documented in the repo.

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

- **No globals.** Fin 0.4.0 has no mutable module-level state, so there is
  no global default logger — configuration lives in an explicit `Logger`
  struct you own and pass by `&`. The per-logger threshold is the filtering
  mechanism: messages below it return before any formatting or I/O, which is
  the same gating a global threshold would give.
- **Levels** are plain ints (0=DEBUG, 1=INFO, 2=WARN, 3=ERROR, 4=FATAL) —
  finc 0.4.0 does not lower `const` declarations from imported modules.
  `logg_level_name()` maps them to readable names.
- **FATAL aborts.** Like `testing::std`'s `assert_*`, FATAL emits the record
  then aborts via `blame` — it is a programmer-facing failure, not a
  recoverable error.
- **Ownership:** `logg_new` keeps (never frees) your `name` and `file_path`
  pointers — string literals are the normal choice. All formatted lines and
  escaped strings are freed internally. `logg_level_name` returns literals:
  do not free them.
- **File output** appends one line per record (`fs::std.append_string`:
  open-append-close per line). Simple and correct; if you log millions of
  lines per second, batch them yourself.

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
| `logg_fields(&l, level, msg, &keys, &vals)` | Structured `key=value` (text) / `"k":"v"` (JSON) fields; `keys[i]` belongs to `vals[i]`; mismatched lengths blame. |

## Dependencies

None beyond the Fin standard library (`collection`, `strings`, `fs`, `time`)
and libc (`snprintf`, `calloc`, `free` — vendored `@define`s, no link flags
needed). Zero third-party packages.

## License

MIT
