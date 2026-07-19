import asyncio
import re
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

try:
    from .platforms import PLATFORMS
except ImportError:
    from platforms import PLATFORMS

app = FastAPI(title="HandleCheck API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,39}$")
CONCURRENCY_LIMIT = 12


def validate_username(username: str) -> str:
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username can't be empty.")
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail="Use 1-39 characters: letters, numbers, underscore, dot, or hyphen.",
        )
    return username


async def run_one(client, sem, platform, username):
    async with sem:
        started = time.monotonic()
        try:
            result = await platform["check"](client, username)
        except Exception:
            result = {"status": "unknown", "note": "checker error"}
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "name": platform["name"],
            "category": platform["category"],
            "url": platform["url"].format(u=username),
            "status": result["status"],
            "note": result.get("note"),
            "elapsed_ms": elapsed_ms,
        }


@app.get("/api/platforms")
async def list_platforms():
    return {
        "count": len(PLATFORMS),
        "platforms": [
            {"name": p["name"], "category": p["category"]} for p in PLATFORMS
        ],
    }


@app.get("/api/check/{username}")
async def check_username(username: str):
    username = validate_username(username)
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

    limits = httpx.Limits(max_connections=CONCURRENCY_LIMIT * 2)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [run_one(client, sem, p, username) for p in PLATFORMS]
        results = await asyncio.gather(*tasks)

    summary = {"available": 0, "taken": 0, "unknown": 0}
    for r in results:
        summary[r["status"]] += 1

    return {
        "username": username,
        "checked_count": len(results),
        "summary": summary,
        "results": results,
    }


# --- Serve the frontend ------------------------------------------------------
# Locally (uvicorn/vercel dev), FRONTEND_DIR exists on disk normally.
# On Vercel, it's only present in the function bundle because vercel.json
# explicitly includes it via "includeFiles": "public/**".
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "public"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def root():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>HandleCheck</h1><p>Frontend not found.</p>", status_code=500)