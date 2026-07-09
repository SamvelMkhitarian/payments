from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.deps import verify_api_key
from app.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    await engine.dispose()


app = FastAPI(title="Payments", lifespan=lifespan)

api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)
app.include_router(api_router)


@app.middleware("http")
async def require_api_key_for_api_routes(request: Request, call_next):
    if request.url.path.startswith("/api/v1"):
        try:
            await verify_api_key(request.headers.get("X-API-Key"))
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )

    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
