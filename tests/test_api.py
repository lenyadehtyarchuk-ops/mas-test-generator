import importlib.util
import unittest
from unittest.mock import patch

HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(HAS_FASTAPI, "FastAPI required for ASGI endpoint tests")
class ApiTests(unittest.TestCase):
    def test_health_and_bad_task(self):
        from fastapi.testclient import TestClient
        from orchestrator.main import app
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.post("/api/v1/task", json={}).status_code, 422)

    def test_agent_contracts_with_fake_llm(self):
        from fastapi.testclient import TestClient
        from agents.analyst.main import app as analyst
        from agents.generator.main import app as generator
        from agents.debugger.main import app as debugger
        from tests.test_pipeline import SPEC, GEN, TEST_FAULT, FAIL
        from common.schemas import SpecificationSchema, GeneratorResponse, DebugReportSchema

        class FakeLLM:
            async def generate_structured(self, system, user, model):
                return model.model_validate({
                    SpecificationSchema: SPEC,
                    GeneratorResponse: GEN,
                    DebugReportSchema: TEST_FAULT,
                }[model])
            async def close(self):
                pass

        base = dict(language="python", source_code="def add(a,b): return a+b")
        cases = [
            (analyst, "/analyze", {**base, "nl_description": "Return sum"}),
            (generator, "/generate", {**base, "specification": SPEC}),
            (debugger, "/triage", {**base, "nl_description": "Return sum",
                                  "specification": SPEC, "test_code": GEN["test_code"],
                                  "execution_result": FAIL}),
        ]
        with patch("common.agent_service.LLMClient", FakeLLM):
            for app, path, payload in cases:
                with TestClient(app) as client:
                    self.assertEqual(client.post(path, json=payload).status_code, 200)
