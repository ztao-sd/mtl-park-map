from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mtl_park_map import settings
from mtl_park_map.api.router import router
from mtl_park_map.store import Store


def create_app(store: Store | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "store"):
            app.state.store = Store.load()
        yield

    app = FastAPI(title="MTL Park Map API", lifespan=lifespan)
    if store is not None:
        app.state.store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.DEV_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
