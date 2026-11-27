from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

import httpx
from openai import BadRequestError, AuthenticationError
from pydantic import ValidationError

from common.llm import LLMClient
from common.schemas import GeneratorResponse
from tests.test_pipeline import complete


def client(mode="auto"):
    llm = LLMClient.__new__(LLMClient)
    llm.model, llm.temperature, llm.mode = "model", 0.1, mode
    llm.client = NS(
        beta=NS(chat=NS(completions=NS(parse=AsyncMock()))),
        chat=NS(completions=NS(create=AsyncMock())),
    )
    return llm


def completion(content):
    return NS(choices=[NS(finish_reason="stop", message=NS(content=content, refusal=None))])


class LLMTests(unittest.TestCase):
    def test_native_parsed_object(self):
        llm = client()
        expected = GeneratorResponse(language="python", test_code="def test_x(): pass")
        llm.client.beta.chat.completions.parse.return_value = NS(
            choices=[NS(message=NS(parsed=expected, refusal=None))])
        actual = complete(llm.generate_structured("system", "data", GeneratorResponse))
        self.assertEqual(actual, expected)
        llm.client.chat.completions.create.assert_not_called()

    def test_format_error_falls_back(self):
        llm = client()
        response = httpx.Response(400, request=httpx.Request("POST", "https://example.test"))
        llm.client.beta.chat.completions.parse.side_effect = BadRequestError(
            "response_format json_schema unsupported", response=response, body=None)
        llm.client.chat.completions.create.return_value = completion(
            '{"language":"python","test_code":"def test_x(): pass"}')
        result = complete(llm.generate_structured("system", "data", GeneratorResponse))
        self.assertEqual(result.language, "python")
        llm.client.chat.completions.create.assert_called_once()

    def test_authentication_never_retried_as_json(self):
        llm = client()
        response = httpx.Response(401, request=httpx.Request("POST", "https://example.test"))
        llm.client.beta.chat.completions.parse.side_effect = AuthenticationError(
            "invalid key", response=response, body=None)
        with self.assertRaises(AuthenticationError):
            complete(llm.generate_structured("system", "data", GeneratorResponse))
        llm.client.chat.completions.create.assert_not_called()

    def test_invalid_schema_rejected(self):
        llm = client("json")
        llm.client.chat.completions.create.return_value = completion('{"bad": true}')
        with self.assertRaises(ValidationError):
            complete(llm.generate_structured("system", "data", GeneratorResponse))

    def test_prompt_mode_has_no_response_format(self):
        llm = client("prompt")
        llm.client.chat.completions.create.return_value = completion(
            '{"language":"python","test_code":"def test_x(): pass"}')
        complete(llm.generate_structured("system", "data", GeneratorResponse))
        self.assertNotIn("response_format", llm.client.chat.completions.create.call_args.kwargs)
