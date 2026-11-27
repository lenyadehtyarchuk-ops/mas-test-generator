"""Deterministic, request-scoped state machine; no LLM in this service."""
import logging
import os
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from common.schemas import (
    AnalystRequest, DebuggerRequest, DebugReportSchema, ExecutionResultSchema,
    ExecutionStatus, GeneratorRequest, GeneratorResponse, IterationHistoryItem,
    RunnerRequest, SpecificationSchema, TargetLanguage, TaskCreateRequest,
    TaskFinalResponse, TaskState, TriageVerdict,
)

class PipelineError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


logger = logging.getLogger(__name__)
ANALYST_URL = os.getenv("ANALYST_URL", "http://agent-analyst:8001")
GENERATOR_URL = os.getenv("GENERATOR_URL", "http://agent-generator:8002")
DEBUGGER_URL = os.getenv("DEBUGGER_URL", "http://agent-debugger:8003")
PYTHON_RUNNER_URL = os.getenv("PYTHON_RUNNER_URL", "http://runner-python:8004")
JAVA_RUNNER_URL = os.getenv("JAVA_RUNNER_URL", "http://runner-java:8005")
AGENT_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "240"))
RUNNER_EXEC_TIMEOUT = int(os.getenv("RUNNER_EXECUTION_TIMEOUT", "10"))


def get_runner_url(language: TargetLanguage) -> str:
    return {
        TargetLanguage.PYTHON: PYTHON_RUNNER_URL,
        TargetLanguage.JAVA: JAVA_RUNNER_URL,
    }[language].rstrip("/") + "/execute"


async def call_service(client, url, payload: BaseModel, model, timeout=None):
    try:
        response = await client.post(url, json=payload.model_dump(mode="json"),
                                     timeout=timeout or AGENT_TIMEOUT)
        response.raise_for_status()
        return model.model_validate(response.json())
    except httpx.TimeoutException as exc:
        raise PipelineError(504, "A pipeline service timed out") from exc
    except (httpx.HTTPError, ValidationError, ValueError) as exc:
        logger.warning("Invalid upstream response: %s", type(exc).__name__)
        raise PipelineError(502, "Pipeline service unavailable or returned an invalid response") from exc


async def run_verification_pipeline(request: TaskCreateRequest) -> TaskFinalResponse:
    task_id = uuid4()
    states = [TaskState.ANALYZING]
    history = []
    previous = feedback = bug_report = fix_result = None
    final_status = "MAX_ITERATIONS_EXCEEDED"
    current_tests = ""
    last_result = None

    # Environment proxy settings must not intercept Docker's internal service names.
    async with httpx.AsyncClient(timeout=AGENT_TIMEOUT, trust_env=False) as client:
        specification = await call_service(
            client, ANALYST_URL + "/analyze",
            AnalystRequest(language=request.language, source_code=request.source_code,
                           nl_description=request.nl_description),
            SpecificationSchema,
        )

        async def execute(source, suffix):
            return await call_service(
                client, get_runner_url(request.language),
                RunnerRequest(task_id=f"{task_id}_{suffix}", source_code=source,
                              test_code=current_tests, timeout_seconds=RUNNER_EXEC_TIMEOUT),
                ExecutionResultSchema, timeout=RUNNER_EXEC_TIMEOUT + 15,
            )

        for iteration in range(1, request.max_iterations + 1):
            states.append(TaskState.GENERATING)
            generated = await call_service(
                client, GENERATOR_URL + "/generate",
                GeneratorRequest(language=request.language, source_code=request.source_code,
                                 specification=specification,
                                 previous_test_code=previous, feedback_error=feedback),
                GeneratorResponse,
            )
            if generated.language != request.language:
                raise PipelineError(502, "Generator returned the wrong language")
            current_tests = generated.test_code
            states.append(TaskState.EXECUTING)
            last_result = await execute(request.source_code, f"iter_{iteration}")
            item = IterationHistoryItem(iteration=iteration, generated_tests=current_tests,
                                        execution_result=last_result)
            history.append(item)
            if last_result.status == ExecutionStatus.PASSED:
                if last_result.passed_tests < 1 or last_result.failed_tests:
                    raise PipelineError(502, "Runner claimed success without passing tests")
                final_status = "ALL_TESTS_PASSED"
                break

            # A malformed source cannot be repaired by rewriting only the tests.
            if (last_result.status == ExecutionStatus.SYNTAX_ERROR
                    and last_result.error_origin == "source"):
                final_status = "SOURCE_ERROR"
                break

            if last_result.status in (ExecutionStatus.SYNTAX_ERROR, ExecutionStatus.TIMEOUT):
                previous = current_tests
                feedback = (
                    f"Runner status: {last_result.status.value}. Correct test syntax/imports "
                    "or accidental loops; do not remove valid cases or mask source defects. "
                    "A timeout can originate in source code; it does not prove a test fault.\n"
                    f"STDERR:\n{last_result.stderr}\nSTDOUT:\n{last_result.stdout}"
                )
                continue

            states.append(TaskState.TRIAGING)
            report = await call_service(
                client, DEBUGGER_URL + "/triage",
                DebuggerRequest(language=request.language, source_code=request.source_code,
                                nl_description=request.nl_description, specification=specification,
                                test_code=current_tests, execution_result=last_result),
                DebugReportSchema,
            )
            item.debug_report = report
            if report.verdict == TriageVerdict.CODE_BUG:
                bug_report = report
                states.append(TaskState.VERIFYING_FIX)
                fix_result = await execute(report.suggested_fix_code, "fix")
                verified = (fix_result.status == ExecutionStatus.PASSED
                            and fix_result.passed_tests > 0 and not fix_result.failed_tests)
                final_status = "BUG_DETECTED_AND_FIXED" if verified else "BUG_DETECTED_FIX_FAILED"
                break

            previous = current_tests
            feedback = f"{report.explanation}\n{report.generator_feedback}"

    states.append(TaskState.FINISHED)
    return TaskFinalResponse(
        task_id=task_id, language=request.language, final_status=final_status,
        iterations_taken=len(history), specification=specification,
        final_test_code=current_tests, last_execution_result=last_result,
        bug_report=bug_report, fix_execution_result=fix_result,
        state_trace=states, history=history,
    )
