"""One disposable analysis process. Run only through the isolated runner service."""

import ctypes
import errno
import json
import math
import os
import resource
import sqlite3
import sys
import traceback


def restrict():
    """Fail closed: kernel syscall allowlist, after loading the numeric libraries."""
    lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x00050000 | errno.EPERM)
    if not context:
        raise RuntimeError("Cannot initialize analysis isolation")
    # No sockets, process creation, exec, ptrace, signals to other processes,
    # namespace changes, capability changes, io_uring, or kernel administration.
    names = """read write readv writev close close_range fstat newfstatat stat lstat
        statx lseek pread64 pwrite64 open openat access faccessat faccessat2 readlink
        readlinkat getdents getdents64 fcntl dup dup2 dup3 ioctl mmap mprotect munmap
        mremap madvise brk msync futex futex_time64 clock_gettime clock_getres
        gettimeofday time nanosleep clock_nanosleep rt_sigaction rt_sigprocmask
        rt_sigreturn sigaltstack getpid getppid gettid getuid geteuid getgid getegid
        getgroups uname sysinfo getrandom sched_yield sched_getaffinity getrlimit
        prlimit64 getrusage restart_syscall exit exit_group chdir getcwd mkdir
        mkdirat unlink unlinkat rmdir rename renameat renameat2 ftruncate truncate
        fsync fdatasync umask""".split()
    try:
        for name in names:
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and lib.seccomp_rule_add(context, 0x7FFF0000, number, 0) != 0:
                raise RuntimeError("Cannot configure analysis isolation")
        if lib.seccomp_load(context) != 0:
            raise RuntimeError("Cannot activate analysis isolation")
    finally:
        lib.seccomp_release(context)


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    import numpy as np
    import pandas as pd
    import statistics
    import datetime

    payload = json.load(sys.stdin)
    restrict()
    inputs = payload["inputs"]
    frames = {}
    for name, value in inputs.items():
        rows = value.get("rows", value.get("series", [])) if isinstance(value, dict) else value
        if isinstance(rows, list):
            frames[name] = pd.DataFrame(rows)
    database = sqlite3.connect(":memory:")
    for name, frame in frames.items():
        # SQL acts only on this run's copies, never on the connected source.
        if len(frame.columns) and not any(frame[c].map(lambda v: isinstance(v, (dict, list))).any() for c in frame):
            frame.to_sql(name, database, index=False)

    def sql(query):
        return pd.read_sql_query(query, database)

    scope = {"pd": pd, "np": np, "inputs": inputs, "frames": frames, "sql": sql,
             "math": math, "statistics": statistics, "datetime": datetime}
    try:
        exec(compile(payload["code"], "<analysis>", "exec"), scope)
        value = scope.get("result")
        if isinstance(value, pd.DataFrame):
            value = {"rows": json.loads(value.to_json(orient="records", date_format="iso"))}
        elif isinstance(value, pd.Series):
            value = json.loads(value.to_json(date_format="iso"))
        def encode(item):
            if isinstance(item, np.generic):
                return item.item()
            if isinstance(item, (datetime.datetime, datetime.date)):
                return item.isoformat()
            raise TypeError(f"Return JSON-compatible values, got {type(item).__name__}")
        rendered = json.dumps({"ok": True, "result": value}, default=encode, ensure_ascii=False, allow_nan=False)
        if len(rendered.encode()) > 4 * 1024 * 1024:
            raise ValueError("Result exceeds 4 MiB; aggregate the data before returning it")
    except BaseException:
        rendered = json.dumps({"ok": False, "error": traceback.format_exc(limit=5)[-5000:]})
    # stdout is a bounded diagnostic log. The structured result is a separate file.
    with open("result.json", "w", encoding="utf-8") as stream:
        stream.write(rendered)


if __name__ == "__main__":
    main()
