import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from common.runner_support import (
    ProcessResult, run_command, child_environment, execution_result, read_test_reports,
)


class RunnerSupportTests(unittest.TestCase):
    def test_process_success_and_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = run_command([sys.executable, "-c", "print('hello')"], root, time.monotonic()+5)
            self.assertEqual(result.exit_code, 0)
            self.assertIn("hello", result.stdout)
            self.assertNotIn("LLM_API_KEY", child_environment(root))

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_command([sys.executable, "-c", "while True: pass"],
                                 Path(folder), time.monotonic()+0.4)
            self.assertTrue(result.timed_out)
            self.assertEqual(result.exit_code, 124)

    def test_output_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_command([sys.executable, "-c", "while True: print('x'*1000)"],
                                 Path(folder), time.monotonic()+5)
            self.assertTrue(result.timed_out)
            self.assertLessEqual(len(result.stdout), 65536)

    def test_xml_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"report.xml"
            path.write_text('<testsuites><testsuite tests="3" failures="1"><testcase name="pass"/>'
                            '<testcase name="fail"><failure type="AssertionError">wrong</failure></testcase>'
                            '<testcase name="skip"><skipped/></testcase></testsuite></testsuites>')
            total, passed, skipped, failures = read_test_reports([path])
            self.assertEqual((total, passed, skipped, len(failures)), (3, 1, 1, 1))
            result = execution_result(ProcessResult(1), [path], time.monotonic())
            self.assertEqual(result.status, "FAILED")

    def test_zero_tests_never_pass(self):
        result = execution_result(ProcessResult(0), [], time.monotonic())
        self.assertEqual(result.status, "SYNTAX_ERROR")

    def test_all_skipped_never_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"report.xml"
            path.write_text('<testsuite><testcase name="x"><skipped/></testcase></testsuite>')
            result = execution_result(ProcessResult(0), [path], time.monotonic())
            self.assertEqual(result.status, "SYNTAX_ERROR")

    def test_entity_report_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"report.xml"
            path.write_text('<!DOCTYPE x [<!ENTITY x "bad">]><testsuite/>')
            with self.assertRaises(ValueError):
                read_test_reports([path])
