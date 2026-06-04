from fastapi import FastAPI

from app.core.lifespan import lifespan

app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
