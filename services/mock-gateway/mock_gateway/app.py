"""HTTP wrapper for the mock AI gateway used by docker-compose. Logs request IDs only."""
from fastapi import FastAPI, Request

from mock_gateway.logic import handle

app = FastAPI(title="NSIP Mock AI Gateway (India region)")


@app.post("/v1/chat/completions")
async def completions(request: Request) -> dict:
    return handle(await request.json())


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "region": "ap-south-1 (mock)"}
