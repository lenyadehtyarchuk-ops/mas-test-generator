"""Bounded subprocess execution and JUnit XML parsing shared by both runners."""
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from common.schemas import ExecutionResultSchema, ExecutionStatus, FailedTestDetail

OUTPUT_LIMIT = 65_536
REPORT_LIMIT = 2_000_000


@dataclass
class ProcessResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


def child_environment(directory: Path) -> dict[str, str]:
    # Never propagate provider credentials, HTTP proxy values or arbitrary host env.
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "JAVA_HOME")
           if key in os.environ}
    env.update(HOME=str(directory), TMPDIR=str(directory), TEMP=str(directory),
               TMP=str(directory), PYTHONPATH=str(directory),
               PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONIOENCODING="utf-8", LANG="C.UTF-8")
    return env


def kill_tree(process):
    try:
        if os.name == "posix":
            # Kill the whole session, including children after their parent exits.
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3, check=False)
    except (ProcessLookupError, PermissionError, subprocess.SubprocessError):
        pass
    finally:
        # taskkill may be unavailable/restricted on a Windows development host.
        # Retain the process handle as an unconditional termination fallback.
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass


def run_command(command: list[str], directory: Path, deadline: float) -> ProcessResult:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return ProcessResult(124, stderr="Execution deadline exceeded", timed_out=True)
    process = subprocess.Popen(
        command, cwd=directory, env=child_environment(directory),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"), bufsize=0,
    )
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()

    def drain(stream, buffer):
        try:
            while chunk := stream.read(4096):
                available = max(0, OUTPUT_LIMIT - len(buffer))
                buffer.extend(chunk[:available])
                if len(chunk) > available:
                    overflow.set()
        except (OSError, ValueError):
            pass
        finally:
            stream.close()

    threads = [
        threading.Thread(target=drain, args=(stream, buffer), daemon=True)
        for stream, buffer in zip((process.stdout, process.stderr), buffers)
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline or overflow.is_set():
                timed_out = True
                break
            try:
                process.wait(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
    finally:
        kill_tree(process)
        process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=2)
    stdout, stderr = (buffer.decode("utf-8", errors="replace") for buffer in buffers)
    if timed_out or overflow.is_set():
        reason = "Output limit exceeded" if overflow.is_set() else "Execution deadline exceeded"
        return ProcessResult(124, stdout, stderr + "\n" + reason, True)
    return ProcessResult(process.returncode, stdout, stderr)


def read_test_reports(paths: list[Path]):
    total = passed = skipped = 0
    failures = []
    for path in paths:
        if path.is_symlink() or path.stat().st_size > REPORT_LIMIT:
            raise ValueError("Invalid test report")
        raw = path.read_bytes()
        if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
            raise ValueError("XML declarations are not accepted in test reports")
        root = ET.fromstring(raw)
        for case in root.iter("testcase"):
            total += 1
            failure = case.find("failure")
            if failure is None:
                failure = case.find("error")
            if failure is not None:
                failures.append(FailedTestDetail(
                    test_name=case.get("classname", "") + "::" + case.get("name", "unknown"),
                    error_type=failure.get("type", failure.tag),
                    message=((failure.get("message", "") + "\n" + (failure.text or ""))[:16_384]),
                ))
            elif case.find("skipped") is not None:
                skipped += 1
            else:
                passed += 1
        # JUnit may report failed containers (e.g. @BeforeAll) with zero testcases.
        declared_failures = sum(int(suite.get("errors", "0")) + int(suite.get("failures", "0"))
                                for suite in root.iter("testsuite"))
        if declared_failures and not failures:
            failures.append(FailedTestDetail(test_name="test_container",
                                            error_type="ContainerError",
                                            message="Test container failed; see stdout/stderr"))
    return total, passed, skipped, failures


def execution_result(process: ProcessResult, reports: list[Path], started: float):
    if process.timed_out:
        status = ExecutionStatus.TIMEOUT
        total = passed = skipped = 0
        failures = []
    else:
        try:
            total, passed, skipped, failures = read_test_reports(reports)
        except (ET.ParseError, ValueError, OSError) as exc:
            total = passed = skipped = 0
            failures = []
            process.stderr += "\nUnreadable test report: " + type(exc).__name__
        if process.exit_code == 0 and passed > 0 and not failures:
            status = ExecutionStatus.PASSED
        elif failures:
            status = ExecutionStatus.FAILED
        else:
            status = ExecutionStatus.SYNTAX_ERROR
            process.stderr += "\nNo executable passing tests or test framework error."
    return ExecutionResultSchema(
        status=status, exit_code=process.exit_code, stdout=process.stdout,
        stderr=process.stderr, total_tests=total, passed_tests=passed,
        skipped_tests=skipped, failed_tests=failures,
        error_origin="tests" if status == ExecutionStatus.SYNTAX_ERROR else None,
        execution_time_ms=(time.monotonic() - started) * 1000,
    )
