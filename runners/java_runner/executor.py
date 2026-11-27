"""JDK 17 + JUnit Jupiter runner; all dependencies are present in the image."""
import os
import tempfile
import threading
import time
from pathlib import Path


from common.runner_support import run_command, execution_result, ProcessResult
from common.schemas import RunnerRequest, ExecutionResultSchema, ExecutionStatus

class RunnerBusy(Exception):
    pass


_gate = threading.Lock()
JUNIT_JAR = Path(os.getenv("JUNIT_JAR", "/opt/junit/junit-platform-console-standalone.jar"))


def execute(request: RunnerRequest):
    if not JUNIT_JAR.is_file():
        raise RunnerBusy("JUnit standalone jar is missing")
    if not _gate.acquire(blocking=False):
        raise RunnerBusy("Runner busy; retry after the current task completes")
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="mas-java-") as temporary:
            directory = Path(temporary)
            (directory / "Solution.java").write_text(request.source_code, encoding="utf-8")
            (directory / "SolutionTest.java").write_text(request.test_code, encoding="utf-8")
            deadline = started + request.timeout_seconds
            # Separate compilation identifies source errors without blaming tests.
            compilation_output = ""
            for filename, origin in (("Solution.java", "source"), ("SolutionTest.java", "tests")):
                compilation = run_command(
                    ["javac", "-J-Xmx128m", "-proc:none", "-encoding", "UTF-8", "--release", "17",
                     "-cp", str(JUNIT_JAR) + os.pathsep + ".", filename],
                    directory, deadline,
                )
                compilation_output += compilation.stdout + compilation.stderr
                if compilation.timed_out or compilation.exit_code:
                    return ExecutionResultSchema(
                        status=ExecutionStatus.TIMEOUT if compilation.timed_out else ExecutionStatus.SYNTAX_ERROR,
                        exit_code=compilation.exit_code, stdout=compilation.stdout,
                        stderr=compilation.stderr, error_origin=origin,
                        execution_time_ms=(time.monotonic() - started) * 1000,
                    )
            process = run_command(
                ["java", "-Xmx128m", "-XX:ActiveProcessorCount=2", "-jar", str(JUNIT_JAR),
                 "execute", "--class-path", ".", "--select-class", "SolutionTest",
                 "--include-engine", "junit-jupiter", "--fail-if-no-tests",
                 "--disable-banner", "--disable-ansi-colors", "--details=summary",
                 "--reports-dir=reports"],
                directory, deadline,
            )
            process.stderr = compilation_output + process.stderr
            return execution_result(process, list((directory / "reports").glob("TEST-*.xml")), started)
    finally:
        _gate.release()
