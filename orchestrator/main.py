from fastapi import FastAPI, HTTPException

from common.schemas import TaskCreateRequest, TaskFinalResponse
from orchestrator.pipeline import PipelineError, run_verification_pipeline

app = FastAPI(title="MAS Orchestrator", version="1.0.0")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "orchestrator"}


@app.post("/api/v1/task", response_model=TaskFinalResponse)
async def create_task(request: TaskCreateRequest):
    try:
        return await run_verification_pipeline(request)
    except PipelineError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
