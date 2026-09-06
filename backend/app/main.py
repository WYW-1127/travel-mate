from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, trips
from app.core.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="TravelMate API")
    s = get_settings()
    origins = [o.strip() for o in s.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(trips.router, prefix="/api")
    return app


app = create_app()
