"""Submit a task JSON without third-party dependencies."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("task", type=Path)
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--output", type=Path)
parser.add_argument("--timeout", type=int, default=1800)
args = parser.parse_args()
data = json.loads(args.task.read_text(encoding="utf-8-sig"))
request = Request(args.url.rstrip("/") + "/api/v1/task",
                  data=json.dumps(data, ensure_ascii=False).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
try:
    with urlopen(request, timeout=args.timeout) as response:
        result = json.load(response)
except HTTPError as exc:
    parser.exit(1, f"HTTP {exc.code}: {exc.read().decode(errors='replace')}\n")
except URLError as exc:
    parser.exit(1, f"Orchestrator unavailable: {exc.reason}\n")
text = json.dumps(result, ensure_ascii=False, indent=2)
print(text)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + "\n", encoding="utf-8")
