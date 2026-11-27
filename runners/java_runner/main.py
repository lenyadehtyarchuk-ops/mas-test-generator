from fastapi import FastAPI, HTTPException

from common.schemas import RunnerRequest, ExecutionResultSchema
from runners.java_runner.executor import execute as run, RunnerBusy, JUNIT_JAR

app = FastAPI(title="MAS Java Runner", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok" if JUNIT_JAR.is_file() else "missing_junit", "service": "runner-java"}


@app.post("/execute", response_model=ExecutionResultSchema)
def execute(request: RunnerRequest):
    try:
        return run(request)
    except RunnerBusy as exc:
        raise HTTPException(503, str(exc)) from exc
