import unittest

from pydantic import ValidationError
from common.schemas import TaskCreateRequest, RunnerRequest, DebugReportSchema, SpecificationSchema


class ContractTests(unittest.TestCase):
    def test_bad_language_and_limits(self):
        for change in ({"language": "ruby"}, {"max_iterations": 0},
                       {"max_iterations": 6}, {"source_code": ""},
                       {"nl_description": "   "}, {"extra_field": True}):
            payload = dict(language="python", source_code="pass", nl_description="A function")
            payload.update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                TaskCreateRequest(**payload)

    def test_timeout_limits(self):
        for timeout in (-1, 0, 31):
            with self.assertRaises(ValidationError):
                RunnerRequest(task_id="x", source_code="pass", test_code="pass",
                              timeout_seconds=timeout)

    def test_verdict_requires_evidence(self):
        for verdict in ("CODE_BUG", "TEST_FAULT"):
            with self.assertRaises(ValidationError):
                DebugReportSchema(verdict=verdict, explanation="Because")

    def test_empty_specification_rejected(self):
        with self.assertRaises(ValidationError):
            SpecificationSchema(function_name="f", inferred_signature="f()",
                                formal_requirements=[], test_scenarios=[])
