#!/usr/bin/env python3
"""Build and exercise the Fin logger, including contracts needing subprocesses."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

if os.name != "nt":
    import resource

WINDOWS = os.name == "nt"
LINUX = sys.platform.startswith("linux")
EXE_SUFFIX = ".exe" if WINDOWS else ""


def console_bytes(raw):
    # Windows CRT text stdout may translate LF to CRLF; binary log files must
    # still pass the byte-exact LF/control checks in records().
    return raw.replace(b"\r\n", b"\n") if WINDOWS else raw


def assert_aborted(result):
    if WINDOWS:
        # UCRT abort normally uses exit(3); error reporting can instead expose
        # STATUS_FATAL_APP_EXIT or a fail-fast status. Require our blame message
        # too so an unrelated nonzero exit does not satisfy the fatal test.
        assert result.returncode in (3, 0x40000015, 0xC0000409), result
    else:
        assert result.returncode == -signal.SIGABRT, result
    assert b"aborting" in result.stderr, result.stderr


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


def windows_peak_rss(child):
    """Read peak working set from this child, without a psutil dependency."""
    import ctypes
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage")]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    # Popen retains its own process handle, so even a very short-lived child's
    # process object remains available while we acquire our independently owned handle.
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, child.pid)
    if not handle:
        child.kill()
        child.wait()
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        child.wait(timeout=60)
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize / 1024
    finally:
        kernel.CloseHandle(handle)
        if child.poll() is None:
            child.kill()
            child.wait()


def measure(binary, work, mode):
    # Native per-child peak memory; never a cumulative maximum over prior tests.
    env = {**os.environ, "LOGG_TEST_MODE": mode}
    start = time.perf_counter()
    with tempfile.TemporaryFile() as err:
        child = subprocess.Popen([str(binary)], cwd=work, env=env,
                                 stdout=subprocess.DEVNULL, stderr=err)
        if WINDOWS:
            rss_kib = windows_peak_rss(child)
        else:
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
            # Linux reports KiB; macOS reports bytes.
            rss_kib = usage.ru_maxrss / (1024 if sys.platform == "darwin" else 1)
        err.seek(0)
        diagnostic = err.read()
    assert child.returncode == 0, (mode, child.returncode, diagnostic)
    assert not diagnostic, diagnostic
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
        assert_aborted(result)
        output = console_bytes(result.stdout)
        assert marker in output and b"FATAL" in output, result
        assert output.count(b"\n") == 1 and b"\r" not in output, output
        if mode == "fatal-json":
            assert json.loads(output)["msg"] == marker.decode()

    result = run(binary, work, "console-success", stdout=subprocess.PIPE)
    assert result.returncode == 0 and not result.stderr, result
    output = console_bytes(result.stdout)
    assert output.count(b"\n") == 1 and b"complete-console-marker" in output, output
    result = run(binary, work, "open-error", stdout=subprocess.PIPE)
    assert result.returncode == 0 and not result.stdout, result
    assert b"output write, close, or flush failed" in result.stderr, result.stderr

    result = run(binary, work, "reject-wrapper", stdout=subprocess.PIPE)
    assert result.returncode == 0 and not result.stdout
    assert b"reserved, duplicate, or null field key" in result.stderr
    if LINUX and Path("/dev/full").exists():
        result = run(binary, work, "full", stdout=subprocess.PIPE)
        assert result.returncode == 0 and not result.stdout
        assert b"output write, close, or flush failed" in result.stderr
        with open("/dev/full", "wb", buffering=0) as full:
            result = run(binary, work, "console-error", stdout=full)
        assert result.returncode == 0 and not result.stderr, result.stderr
    else:
        print("  Linux /dev/full checks skipped on this host")

    if LINUX:
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
    if not WINDOWS:
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
            binary = work / ("test_logg" + EXE_SUFFIX)
            subprocess.run(common + [optimization, str(repo / "tests/test_logg.fin"),
                                     "-o", str(binary)], check=True)
            print(optimization, flush=True)
            validate(binary, work)
            example = work / ("example" + EXE_SUFFIX)
            subprocess.run(common + [optimization, str(repo / "examples/basic.fin"),
                                     "-o", str(example)], check=True)
            result = run(example, work, stdout=subprocess.PIPE)
            assert result.returncode == 0 and not result.stderr, result
            assert len(records(work / "example.log")) == 2
    print("logg: O0/O2 tests, JSON parsing, fatal/error subprocesses, and benchmarks passed")


if __name__ == "__main__":
    main()
