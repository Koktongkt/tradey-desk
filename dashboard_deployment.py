#!/usr/bin/env python3
"""Private, typed dashboard deployment boundary; never relay child output."""
from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
VERCEL_VERSION = "63.1.2"
TOTAL_BUDGET = 290.0  # Leave ten seconds for the executor's 300s envelope.
ATTEMPT_TIMEOUT = 90.0
BACKOFFS = (2.0, 4.0)
OUTPUT_LIMIT = 65536
RETENTION = 30
CLASSES = frozenset({"success", "failed", "auth", "config", "build", "network",
                     "rate_limit", "service", "timeout", "cli_missing"})
TRANSIENT = frozenset({"network", "rate_limit", "service", "timeout"})
RECORD_NAME = re.compile(r"attempt-[0-9]+-[0-9a-f]{32}\.json")


def run_attempt(cmd: list[str], root: Path, timeout: float) -> subprocess.CompletedProcess:
    """Guardian acknowledgement proves cleanup on every exit, including SIGKILL."""
    from dashboard_process import run_owned
    return run_owned(cmd, root, timeout)


def _collect_attempt(cmd: list[str], root: Path, timeout: float) -> subprocess.CompletedProcess:
    """Bound raw output before it reaches the isolated subreaper protocol."""
    deadline = time.monotonic() + max(0.001, timeout)
    try:
        proc = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess([], 127, "", "")
    except OSError:
        return subprocess.CompletedProcess([], 126, "", "")
    output = bytearray()
    observed = set()
    timed_out = False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map() or proc.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 8192)
                    if chunk:
                        # Carry categories across discarded output: a late HTTP
                        # error must not turn an earlier permanent error into a retry.
                        window = bytes(output[-256:]) + chunk
                        observed.add(classify("deploy", subprocess.CompletedProcess(
                            [], 1, window.decode("utf-8", errors="replace"), "")))
                        output.extend(chunk)
                        del output[:-OUTPUT_LIMIT]
                    else:
                        selector.unregister(key.fileobj)
    finally:
        # Grandchildren holding the pipe must not survive a timeout either.
        if timed_out or proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait(timeout=1)
        proc.stdout.close()
    result = subprocess.CompletedProcess([], 124 if timed_out else proc.returncode,
                                         output.decode("utf-8", errors="replace"), "")
    result.observed_classifications = frozenset(observed)
    return result


def classify(stage: str, result: subprocess.CompletedProcess) -> str:
    """Allowlisted categories only. Permanent errors outrank transient markers."""
    if result.returncode == 0:
        return "success"
    if stage == "build":
        return "timeout" if result.returncode == 124 else "failed"
    observed = getattr(result, "observed_classifications", ())
    for permanent in ("auth", "config", "build"):
        if permanent in observed:
            return permanent
    if result.returncode == 124:
        return "timeout"
    if result.returncode == 127:
        return "cli_missing"
    if result.returncode == 126:
        return "config"
    text = result.stdout.lower()
    patterns = (
        ("auth", r"invalid (?:token|credentials)|(?:token|credentials) (?:is |are )?(?:invalid|not valid)|no existing credentials|must be logged in|not (?:logged in|authorized)|authentication (?:failed|required)|unauthorized|forbidden|\bhttp (?:401|403)\b"),
        ("config", r"permission denied|\beacces\b|project (?:not found|does not exist)|no such project|invalid (?:configuration|config|argument)|missing (?:configuration|project)|unknown option"),
        ("build", r"build failed|build (?:error|failure)|command .{0,100} exited with (?:code )?[1-9]|compilation failed"),
        ("rate_limit", r"\bhttp 429\b|too many requests|rate limit(?:ed| exceeded)"),
        ("service", r"\bhttp 50[0234]\b|service unavailable|bad gateway|gateway timeout"),
        ("network", r"\b(?:econnreset|etimedout|eai_again|econnrefused)\b"),
    )
    for classification, pattern in patterns:
        if classification in observed or re.search(pattern, text):
            return classification
    return "failed"


def record_attempt(root: Path, stage: str, attempt: int, rc: int,
                   duration: float, classification: str) -> None:
    """Best effort: store structured categories, not redacted free-form text."""
    fd = None
    parent_fd = None
    try:
        if stage not in {"build", "deploy"} or classification not in CLASSES:
            return
        # Root is trusted; every private component is opened relative to its
        # already validated parent, refusing symlinks and foreign ownership.
        parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for component in ('private', 'dashboard_deploy_diagnostics'):
            try:
                os.mkdir(component, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=parent_fd)
            if os.fstat(fd).st_uid != os.getuid():
                return
            os.fchmod(fd, 0o700)
            os.close(parent_fd)
            parent_fd, fd = fd, None
        fd, parent_fd = parent_fd, None
        # Nonblocking lock bounds concurrent retention work and avoids I/O waits.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        name = f"attempt-{time.time_ns()}-{uuid.uuid4().hex}.json"
        row = {"stage": stage, "attempt": attempt, "returncode": rc,
               "duration_ms": round(duration * 1000), "classification": classification}
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      0o600, dir_fd=fd)
        with os.fdopen(out, "w") as stream:
            json.dump(row, stream, sort_keys=True)
            stream.write("\n")
        records = []
        for entry in os.listdir(fd):
            if not RECORD_NAME.fullmatch(entry):
                continue
            info = os.stat(entry, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1:
                records.append(entry)
        for entry in sorted(records, key=lambda value: int(value.split("-")[1]))[:-RETENTION]:
            # Unlink acts on the directory entry, never on a symlink target.
            os.unlink(entry, dir_fd=fd)
    except Exception:
        pass
    finally:
        for handle in (fd, parent_fd):
            if handle is not None:
                try:
                    os.close(handle)
                except OSError:
                    pass


def deploy(root: Path = ROOT) -> int:
    deadline = time.monotonic() + TOTAL_BUDGET
    command = ["npx", "--yes", f"--package=vercel@{VERCEL_VERSION}", "--",
               "vercel", "deploy", str(root / "public"), "--prod", "--yes"]
    if os.environ.get("VERCEL_TOKEN"):
        command.extend(["--token", os.environ["VERCEL_TOKEN"]])
    for stage, cmd in (("build", [sys.executable, str(root / "public_dashboard.py")]),
                       ("deploy", command)):
        for attempt in range(1, 4 if stage == "deploy" else 2):
            started = time.monotonic()
            remaining = deadline - started
            result = (run_attempt(cmd, root, min(ATTEMPT_TIMEOUT, remaining)) if remaining > 0
                      else subprocess.CompletedProcess([], 124, "", ""))
            classification = classify(stage, result)
            try:
                record_attempt(root, stage, attempt, result.returncode,
                               time.monotonic()-started, classification)
            except Exception:
                pass  # Diagnostics are never part of the deployment result.
            if classification == "success":
                break
            if stage == "deploy" and classification in TRANSIENT and attempt <= len(BACKOFFS):
                delay = BACKOFFS[attempt-1]
                if deadline - time.monotonic() > delay:
                    time.sleep(delay)
                    continue
            token = "dashboard_cli_missing" if classification == "cli_missing" else f"dashboard_{stage}_{classification}"
            print(f"SYSTEM_FAILURE {token}")
            return 1
    return 0


def main() -> int:
    try:
        return deploy()
    except Exception:
        # Even unexpected failures must not leak paths, arguments or raw stderr.
        print("SYSTEM_FAILURE dashboard_deploy_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
