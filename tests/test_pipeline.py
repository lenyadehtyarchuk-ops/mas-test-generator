import asyncio
import unittest
from unittest.mock import patch

import httpx

from common.schemas import TaskCreateRequest
from orchestrator import pipeline

SPEC = dict(function_name="add", inferred_signature="add(a,b)",
            formal_requirements=["Return a+b"], test_scenarios=[
                dict(id="TC-1", scenario_type="positive", description="sum",
                     input_data="1,2", expected_behavior="3")])
GEN = dict(language="python", test_code="from solution import add\ndef test_sum(): assert add(1,2)==3")
PASS = dict(status="PASSED", exit_code=0, total_tests=1, passed_tests=1)
FAIL = dict(status="FAILED", exit_code=1, total_tests=1, passed_tests=0,
            failed_tests=[dict(test_name="test_sum", error_type="AssertionError", message="-1 != 3")])
TEST_FAULT = dict(verdict="TEST_FAULT", explanation="Wrong expectation", generator_feedback="Expect 3")
CODE_BUG = dict(verdict="CODE_BUG", explanation="Subtracts instead of adding",
                bug_location_line=2, root_cause="Wrong operator",
                suggested_fix_code="def add(a,b):\n    return a+b\n")


class FakeClient:
    def __init__(self, executions, verdict=None, malformed=None):
        self.executions = list(executions)
        self.verdict = verdict
        self.malformed = malformed
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json, **kwargs):
        self.calls.append((url, json))
        request = httpx.Request("POST", url)
        if self.malformed:
            return httpx.Response(200, json=self.malformed, request=request)
        if url.endswith("/analyze"):
            data = SPEC
        elif url.endswith("/generate"):
            data = {**GEN, "language": json["language"]}
        elif url.endswith("/triage"):
            data = self.verdict
        else:
            data = self.executions.pop(0)
        return httpx.Response(200, json=data, request=request)


def complete(coroutine):
    # All service calls are immediate in-memory fakes. Assert no real I/O occurs.
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coroutine.close()
    raise AssertionError("Unexpected asynchronous I/O in deterministic unit test")


class PipelineTests(unittest.TestCase):
    def run_pipeline(self, executions, verdict=None, language="python", maximum=3):
        fake = FakeClient(executions, verdict)
        with patch.object(pipeline.httpx, "AsyncClient", return_value=fake):
            result = complete(pipeline.run_verification_pipeline(TaskCreateRequest(
                language=language, source_code="def add(a,b): return a-b",
                nl_description="Return a+b", max_iterations=maximum)))
        return result, fake

    def test_success(self):
        result, client = self.run_pipeline([PASS])
        self.assertEqual(result.final_status, "ALL_TESTS_PASSED")
        self.assertEqual(result.iterations_taken, 1)
        self.assertFalse(any(url.endswith("/triage") for url, _ in client.calls))

    def test_technical_feedback_without_debugger(self):
        for status in ("SYNTAX_ERROR", "TIMEOUT"):
            result, client = self.run_pipeline([
                dict(status=status, exit_code=2, stderr="broken tests", error_origin="tests"), PASS])
            self.assertEqual(result.iterations_taken, 2)
            self.assertFalse(any(url.endswith("/triage") for url, _ in client.calls))
            generated = [data for url, data in client.calls if url.endswith("/generate")]
            self.assertIn("broken tests", generated[1]["feedback_error"])
            self.assertEqual(generated[1]["previous_test_code"], GEN["test_code"])

    def test_semantic_feedback(self):
        result, client = self.run_pipeline([FAIL, PASS], TEST_FAULT)
        self.assertEqual(result.final_status, "ALL_TESTS_PASSED")
        self.assertEqual(result.history[0].debug_report.verdict, "TEST_FAULT")
        self.assertEqual(sum(url.endswith("/analyze") for url, _ in client.calls), 1)

    def test_fix_is_executed(self):
        result, client = self.run_pipeline([FAIL, PASS], CODE_BUG)
        self.assertEqual(result.final_status, "BUG_DETECTED_AND_FIXED")
        requests = [data for url, data in client.calls if url.endswith("/execute")]
        self.assertEqual(requests[-1]["source_code"], CODE_BUG["suggested_fix_code"])
        self.assertEqual(result.last_execution_result.status, "FAILED")
        self.assertEqual(result.fix_execution_result.status, "PASSED")

    def test_failed_fix_never_claims_success(self):
        result, _ = self.run_pipeline([FAIL, FAIL], CODE_BUG)
        self.assertEqual(result.final_status, "BUG_DETECTED_FIX_FAILED")

    def test_exhaustion(self):
        result, _ = self.run_pipeline([FAIL, FAIL], TEST_FAULT, maximum=2)
        self.assertEqual(result.final_status, "MAX_ITERATIONS_EXCEEDED")
        self.assertEqual(len(result.history), 2)

    def test_source_syntax_not_blames_generator(self):
        result, client = self.run_pipeline([
            dict(status="SYNTAX_ERROR", exit_code=2, error_origin="source")])
        self.assertEqual(result.final_status, "SOURCE_ERROR")
        self.assertEqual(result.iterations_taken, 1)

    def test_java_route(self):
        result, client = self.run_pipeline([PASS], language="java")
        self.assertTrue(any("runner-java" in url for url, _ in client.calls))

    def test_invalid_upstream_is_502(self):
        fake = FakeClient([], malformed={"wrong": "schema"})
        with patch.object(pipeline.httpx, "AsyncClient", return_value=fake):
            with self.assertRaises(pipeline.PipelineError) as caught:
                complete(pipeline.run_verification_pipeline(TaskCreateRequest(
                    language="python", source_code="pass", nl_description="x")))
        self.assertEqual(caught.exception.status_code, 502)

    def test_transport_errors(self):
        for error, code in ((httpx.ReadTimeout("slow"), 504), (httpx.ConnectError("offline"), 502)):
            class BrokenClient(FakeClient):
                async def post(self, *args, **kwargs):
                    raise error
            with patch.object(pipeline.httpx, "AsyncClient", return_value=BrokenClient([])):
                with self.assertRaises(pipeline.PipelineError) as caught:
                    complete(pipeline.run_verification_pipeline(TaskCreateRequest(
                        language="python", source_code="pass", nl_description="x")))
            self.assertEqual(caught.exception.status_code, code)

    def test_fake_pass_rejected(self):
        with self.assertRaises(pipeline.PipelineError):
            self.run_pipeline([dict(status="PASSED", exit_code=0, total_tests=0, passed_tests=0)])
