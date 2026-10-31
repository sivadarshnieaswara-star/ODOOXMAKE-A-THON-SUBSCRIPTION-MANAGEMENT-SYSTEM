import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .database import Base, SessionLocal, engine
from .routers import auth_router, billing_router, catalog_router, product_router, staff_router, subscription_router
from .seed_data import bootstrap_admin, seed_demo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        bootstrap_admin(db)
        if config.SEED_DEMO_DATA:
            seed_demo(db)
    yield


app = FastAPI(title="Brightloop Subscription Management System", version="1.0.0", lifespan=lifespan)

for r in (auth_router, staff_router, product_router, catalog_router, subscription_router, billing_router):
    app.include_router(r.router)

app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.FRONTEND_DIR / "templates" / "index.html")


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}
