#!/usr/bin/env python3
"""Build and exercise the Fin logger, including contracts needing subprocesses."""
import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import tempfile
import time


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f"duplicate JSON key: {key!r}"
        result[key] = value
    return result


def records(path):
    raw = path.read_bytes()
    assert raw.endswith(b"\n"), path
    lines = raw.split(b"\n")[:-1]
    for line in lines:
        assert all(byte >= 32 and byte != 127 for byte in line), repr(line)
    return [json.loads(line, object_pairs_hook=unique_object) for line in lines]


def run(binary, work, mode=None, **kwargs):
    env = dict(os.environ)
    env.pop("LOGG_TEST_MODE", None)
    if mode:
        env["LOGG_TEST_MODE"] = mode
    env.update(kwargs.pop("extra_env", {}))
    return subprocess.run([str(binary)], cwd=work, env=env, timeout=60,
                          stderr=subprocess.PIPE, **kwargs)


def measure(binary, work, mode):
    # wait4 supplies this child's peak RSS rather than a cumulative child maximum.
    env = {**os.environ, "LOGG_TEST_MODE": mode}
    start = time.perf_counter()
    with tempfile.TemporaryFile() as err:
        child = subprocess.Popen([str(binary)], cwd=work, env=env,
                                 stdout=subprocess.DEVNULL, stderr=err)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        err.seek(0)
        diagnostic = err.read()
    assert child.returncode == 0, (mode, child.returncode, diagnostic)
    assert not diagnostic, diagnostic
    # Linux reports KiB; macOS reports bytes.
    rss_kib = usage.ru_maxrss / (1024 if os.uname().sysname == "Darwin" else 1)
    return time.perf_counter() - start, rss_kib


def validate(binary, work):
    result = run(binary, work, stdout=subprocess.PIPE)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert not result.stderr, result.stderr
    assert b"all tests passed" in result.stdout
    assert b"you should NOT see" not in result.stdout
    ordinary = records(work / "logg-json.log")
    assert len(ordinary) == 1
    assert ordinary[0]["user"] == 'say "hi"'
    payload = "".join(map(chr, range(1, 32))) + chr(127) + ' café \\" = \u0085  '
    escaped = records(work / "logg-controls.jsonl")
    assert len(escaped) == 1
    assert escaped[0]["logger"] == payload, repr(escaped[0]["logger"])
    assert escaped[0]["msg"] == payload
    assert escaped[0][payload] == payload
    raw = (work / "logg-controls.txt").read_bytes()
    assert raw.count(b"\n") == 1 and raw.endswith(b"\n"), raw
    assert all(b >= 32 and b != 127 for b in raw[:-1]), raw
    assert b"\\u0085" in raw and b"\\u2028" in raw and b"\\u2029" in raw
    accepted = records(work / "logg-rejected.jsonl")
    assert len(accepted) == 2
    assert accepted[0]["level"] == "ERROR" and accepted[0]["user"] == "spoofed"
    assert accepted[1]["level"] == "FATAL"

    for mode, marker in (("fatal", b"fatal-marker"), ("fatal-json", b"fatal-fields-marker")):
        result = run(binary, work, mode, stdout=subprocess.PIPE)
        assert result.returncode == -signal.SIGABRT, result
        assert marker in result.stdout and b"FATAL" in result.stdout, result
        assert b"aborting" in result.stderr, result.stderr
        assert result.stdout.count(b"\n") == 1, result.stdout
        if mode == "fatal-json":
            assert json.loads(result.stdout)["msg"] == marker.decode()

    result = run(binary, work, "reject-wrapper", stdout=subprocess.PIPE)
    assert result.returncode == 0 and not result.stdout
    assert b"reserved, duplicate, or null field key" in result.stderr
    if Path("/dev/full").exists():
        result = run(binary, work, "full", stdout=subprocess.PIPE)
        assert result.returncode == 0 and not result.stdout
        assert b"output write, close, or flush failed" in result.stderr
        with open("/dev/full", "wb", buffering=0) as full:
            result = run(binary, work, "console-error", stdout=full)
        assert result.returncode == 0 and not result.stderr, result.stderr
    else:
        print("  /dev/full unavailable: device failure checks skipped")

    if os.uname().sysname == "Linux":
        shim = work / "io_faults.so"
        subprocess.run(["cc", "-shared", "-fPIC", str(Path(__file__).with_name("io_faults.c")),
                        "-o", str(shim), "-ldl"], check=True)
        for fault, mode in (("short-eintr", "console-success"),
                            ("zero-write", "console-error"), ("flush-error", "console-error")):
            result = run(binary, work, mode, stdout=subprocess.PIPE,
                         extra_env={"LD_PRELOAD": str(shim), "LOGG_IO_FAULT": fault})
            assert result.returncode == 0 and not result.stderr, (fault, result)
            if fault == "short-eintr":
                assert result.stdout.count(b"\n") == 1 and b"complete-console-marker" in result.stdout

    _, baseline = measure(binary, work, "baseline")
    elapsed, filtered = measure(binary, work, "filtered")
    assert filtered - baseline < 12 * 1024, (baseline, filtered)
    assert not (work / "filtered-must-not-exist.log").exists()
    small_time, small_rss = measure(binary, work, "long")
    large_time, large_rss = measure(binary, work, "long-double")
    assert max(small_rss, large_rss) - baseline < 12 * 1024, (baseline, small_rss, large_rss)
    print(f"  million filtered: {elapsed:.4f}s, peak {filtered:.0f} KiB (baseline {baseline:.0f})")
    print(f"  2,000 JSON records: 16KiB {small_time:.3f}s / 32KiB {large_time:.3f}s; "
          f"peak {small_rss:.0f}/{large_rss:.0f} KiB")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finc", default=os.environ.get("FINC", "finc"))
    parser.add_argument("--fin-libs", default=os.environ.get("FIN_LIBS"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    common = [args.finc, "-I", str(repo / "src")]
    if args.fin_libs:
        common += ["--fin-libs", args.fin_libs]
    subprocess.run(common + [str(repo / "src/logg.fin")], check=True)
    with tempfile.TemporaryDirectory(prefix=".logg-tests-", dir=repo) as directory:
        root = Path(directory)
        for optimization in ("-O0", "-O2"):
            work = root / optimization[1:]
            work.mkdir()
            binary = work / "test_logg"
            subprocess.run(common + [optimization, str(repo / "tests/test_logg.fin"),
                                     "-o", str(binary)], check=True)
            print(optimization, flush=True)
            validate(binary, work)
            example = work / "example"
            subprocess.run(common + [optimization, str(repo / "examples/basic.fin"),
                                     "-o", str(example)], check=True)
            result = run(example, work, stdout=subprocess.PIPE)
            assert result.returncode == 0 and not result.stderr, result
            assert len(records(work / "example.log")) == 2
    print("logg: O0/O2 tests, JSON parsing, fatal/error subprocesses, and benchmarks passed")


if __name__ == "__main__":
    main()
