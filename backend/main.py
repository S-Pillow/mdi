import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mdi")

app = FastAPI(
    title="MDI — Malicious Domain Identifier API",
    description="Shell only. Functionality not yet implemented.",
    version="shell",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/mdi/health", tags=["Health"])
async def health():
    """Service health check. Returns ok when the backend is running."""
    return {"status": "ok", "service": "mdi", "version": "shell"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8011, reload=True)
