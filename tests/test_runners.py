import importlib.util
import os
from pathlib import Path
import shutil
import unittest

from common.schemas import RunnerRequest
from runners.python_runner.executor import execute as python_execute
from runners.java_runner.executor import execute as java_execute, JUNIT_JAR

HAS_PYTEST = importlib.util.find_spec("pytest") is not None
HAS_JAVA = bool(shutil.which("javac") and shutil.which("java") and JUNIT_JAR.is_file())
PY_SOURCE = "def add(a,b):\n    return a+b\n"
PY_TEST = "from solution import add\ndef test_add():\n    assert add(1,2)==3\n"
JAVA_SOURCE = "public class Solution { public static int add(int a,int b) { return a+b; } }"
JAVA_TEST = ("import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; "
             "class SolutionTest { @Test void adds() { assertEquals(3,Solution.add(1,2)); } }")


def request(source, test, timeout=10):
    return RunnerRequest(task_id="../../path-is-not-used", source_code=source,
                         test_code=test, timeout_seconds=timeout)


class PythonSyntaxTests(unittest.TestCase):
    def test_bad_source(self):
        result = python_execute(request("def add(:", PY_TEST))
        self.assertEqual((result.status, result.error_origin), ("SYNTAX_ERROR", "source"))

    def test_bad_tests(self):
        result = python_execute(request(PY_SOURCE, "def test_(:"))
        self.assertEqual((result.status, result.error_origin), ("SYNTAX_ERROR", "tests"))


@unittest.skipUnless(HAS_PYTEST, "pytest must be installed for real Python execution")
class PythonRunnerTests(unittest.TestCase):
    def test_pass_and_failure_counts(self):
        for source, status, passed in ((PY_SOURCE, "PASSED", 1),
                                     (PY_SOURCE.replace("a+b", "a-b"), "FAILED", 0)):
            result = python_execute(request(source, PY_TEST))
            self.assertEqual(result.status, status, result.model_dump())
            self.assertEqual((result.total_tests, result.passed_tests), (1, passed))

    def test_no_tests(self):
        result = python_execute(request(PY_SOURCE, "# no tests\n"))
        self.assertEqual(result.status, "SYNTAX_ERROR")

    def test_timeout(self):
        result = python_execute(request(PY_SOURCE, "def test_loop():\n    while True: pass", 2))
        self.assertEqual(result.status, "TIMEOUT")


@unittest.skipUnless(HAS_JAVA, "JDK 17 and JUNIT_JAR required (available in runner-java image)")
class JavaRunnerTests(unittest.TestCase):
    def test_pass_and_failure(self):
        for source, status in ((JAVA_SOURCE, "PASSED"),
                               (JAVA_SOURCE.replace("a+b", "a-b"), "FAILED")):
            result = java_execute(request(source, JAVA_TEST, 30))
            self.assertEqual(result.status, status, result.model_dump())
            self.assertEqual(result.total_tests, 1)

    def test_source_compilation_error(self):
        result = java_execute(request("public class Solution { broken }", JAVA_TEST, 30))
        self.assertEqual((result.status, result.error_origin), ("SYNTAX_ERROR", "source"))

    def test_test_compilation_error(self):
        result = java_execute(request(JAVA_SOURCE, "class SolutionTest { broken }", 30))
        self.assertEqual((result.status, result.error_origin), ("SYNTAX_ERROR", "tests"))

    def test_no_tests(self):
        result = java_execute(request(JAVA_SOURCE, "class SolutionTest {}", 30))
        self.assertEqual(result.status, "SYNTAX_ERROR")

    def test_timeout(self):
        source = JAVA_SOURCE.replace("return a+b;", "while(true) {}")
        result = java_execute(request(source, JAVA_TEST, 5))
        self.assertEqual(result.status, "TIMEOUT")
