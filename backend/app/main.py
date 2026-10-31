import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session
from fastapi.staticfiles import StaticFiles

from . import config
from .database import Base, SessionLocal, add_missing_columns, engine, get_db
from .routers import (
    auth_router, billing_router, catalog_router, forecast_router, portal_router, product_router, recommendation_router,
    staff_router, subscription_router,
)
from .seed_data import bootstrap_admin, seed_demo
from .services.blackbox import backfill_missing
from .services.customer_features import verify_pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    with SessionLocal() as db:
        bootstrap_admin(db)
        if config.SEED_DEMO_DATA:
            seed_demo(db)
        backfill_missing(db)   # subscriptions created before the black box existed get a reconstructed record
    yield


app = FastAPI(title="Brightloop Subscription Management System", version="1.0.0", lifespan=lifespan)

for r in (auth_router, staff_router, product_router, catalog_router, subscription_router, billing_router, forecast_router,
          recommendation_router, portal_router):
    app.include_router(r.router)

app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.FRONTEND_DIR / "templates" / "index.html")


_pass_page = Environment(loader=FileSystemLoader(config.FRONTEND_DIR / "templates"), autoescape=select_autoescape())


@app.get("/pass/{token}", response_class=HTMLResponse, include_in_schema=False)
def pass_page(token: str, db: Session = Depends(get_db)):
    """What someone sees after scanning a customer's QR pass."""
    return _pass_page.get_template("pass_verify.html").render(r=verify_pass(db, token))


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}
