import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.mdi import router as mdi_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mdi")

app = FastAPI(
    title="MDI — Malicious Domain Identifier API",
    description="Standalone Forge Forward tool. See /api/mdi/health for status.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(mdi_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8011, reload=True)
