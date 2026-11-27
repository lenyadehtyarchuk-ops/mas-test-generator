"""pytest runner. Deploy only inside the isolated Compose sandbox."""
import ast
import sys
import tempfile
import threading
import time
from pathlib import Path


from common.runner_support import run_command, execution_result
from common.schemas import RunnerRequest, ExecutionResultSchema, ExecutionStatus

class RunnerBusy(Exception):
    pass


_gate = threading.Lock()


def execute(request: RunnerRequest):
    if not _gate.acquire(blocking=False):
        raise RunnerBusy("Runner busy; retry after the current task completes")
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="mas-python-") as temporary:
            directory = Path(temporary)
            for filename, code, origin in (
                ("solution.py", request.source_code, "source"),
                ("test_solution.py", request.test_code, "tests"),
            ):
                try:
                    ast.parse(code, filename=filename)
                except (SyntaxError, ValueError, RecursionError) as exc:
                    return ExecutionResultSchema(
                        status=ExecutionStatus.SYNTAX_ERROR, exit_code=2,
                        stderr=str(exc), error_origin=origin,
                        execution_time_ms=(time.monotonic() - started) * 1000,
                    )
                (directory / filename).write_text(code, encoding="utf-8")
            # Explicit test file, no plugin autoload or parent project configuration.
            (directory / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            process = run_command(
                [sys.executable, "-m", "pytest", "-q", "-s", "--tb=short",
                 "--color=no", "-p", "no:cacheprovider", "-c", "pytest.ini",
                 "--junitxml=report.xml", "test_solution.py"],
                directory, started + request.timeout_seconds,
            )
            report = directory / "report.xml"
            result = execution_result(process, [report] if report.exists() else [], started)
            if not process.timed_out and process.exit_code in (2, 3, 4, 5):
                result.status = ExecutionStatus.SYNTAX_ERROR
                result.error_origin = "tests"
            return result
    finally:
        _gate.release()
