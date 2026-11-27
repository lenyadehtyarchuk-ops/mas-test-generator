"""Exercise real sandbox containers without calling an LLM provider."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PY = "def add(a,b):\n    return a+b\n"
PT = "from solution import add\ndef test_add(): assert add(1,2)==3\n"
JAVA = "public class Solution { public static int add(int a,int b) { return a+b; } }"
JT = ("import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; "
      "class SolutionTest { @Test void adds() { assertEquals(3,Solution.add(1,2)); } }")
CASES = [
    ("python pass", "runner-python", 8004, PY, PT, "PASSED", 10),
    ("python bug", "runner-python", 8004, PY.replace("a+b", "a-b"), PT, "FAILED", 10),
    ("python syntax", "runner-python", 8004, PY, "def test_(:", "SYNTAX_ERROR", 10),
    ("python empty", "runner-python", 8004, PY, "# no tests", "SYNTAX_ERROR", 10),
    ("python timeout", "runner-python", 8004, PY, "def test_loop():\n    while True: pass", "TIMEOUT", 2),
    ("java pass", "runner-java", 8005, JAVA, JT, "PASSED", 30),
    ("java bug", "runner-java", 8005, JAVA.replace("a+b", "a-b"), JT, "FAILED", 30),
    ("java syntax", "runner-java", 8005, JAVA, "class SolutionTest { broken }", "SYNTAX_ERROR", 30),
    ("java empty", "runner-java", 8005, JAVA, "class SolutionTest {}", "SYNTAX_ERROR", 30),
    ("java timeout", "runner-java", 8005, JAVA.replace("return a+b;", "while(true) {}"), JT, "TIMEOUT", 5),
]


def main():
    failed = 0
    for name, service, port, source, tests, expected, timeout in CASES:
        payload = dict(task_id="smoke", source_code=source, test_code=tests, timeout_seconds=timeout)
        # The command is an argument list, never shell interpolation. JSON is embedded
        # as a Python string literal, not executable user input.
        script = (
            "import json,urllib.request\n"
            f"payload=json.loads({json.dumps(json.dumps(payload))})\n"
            f"request=urllib.request.Request('http://{service}:{port}/execute',"
            "data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})\n"
            "with urllib.request.urlopen(request,timeout=45) as r: print(r.read().decode())\n"
        )
        completed = subprocess.run(
            ["docker", "compose", "exec", "-T", "orchestrator", "python", "-"],
            input=script, text=True, encoding="utf-8", capture_output=True, cwd=ROOT, timeout=60,
        )
        if completed.returncode:
            print(f"FAIL {name}: {completed.stderr}")
            failed += 1
            continue
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            print(f"FAIL {name}: non-JSON output")
            failed += 1
            continue
        ok = result["status"] == expected
        if expected == "PASSED":
            ok = ok and result["passed_tests"] > 0
        print(f"{'OK' if ok else 'FAIL'} {name}: {result['status']}")
        if not ok:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            failed += 1

    # Validate outbound network isolation from each runner.
    probe = (
        "import socket,sys\n"
        "try:\n"
        " s=socket.create_connection(('1.1.1.1',443),timeout=2)\n"
        "except OSError:\n"
        " print('outbound blocked'); sys.exit(0)\n"
        "else:\n"
        " s.close(); print('outbound unexpectedly available'); sys.exit(1)\n"
    )
    for service in ("runner-python", "runner-java"):
        checked = subprocess.run(
            ["docker", "compose", "exec", "-T", service, "python", "-"],
            input=probe, text=True, encoding="utf-8", capture_output=True, cwd=ROOT, timeout=10,
        )
        ok = checked.returncode == 0 and "outbound blocked" in checked.stdout
        print(f"{'OK' if ok else 'FAIL'} {service} internet isolation")
        failed += not ok
    return int(bool(failed))


if __name__ == "__main__":
    sys.exit(main())
