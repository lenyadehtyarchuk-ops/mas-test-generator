from fastapi import FastAPI, HTTPException

from common.schemas import RunnerRequest, ExecutionResultSchema
from runners.python_runner.executor import execute as run, RunnerBusy

app = FastAPI(title="MAS Python Runner", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "runner-python"}


@app.post("/execute", response_model=ExecutionResultSchema)
def execute(request: RunnerRequest):
    try:
        return run(request)
    except RunnerBusy as exc:
        raise HTTPException(503, str(exc)) from exc
