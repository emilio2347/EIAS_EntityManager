"""EIAS Entity Manager — FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import create_tables
from app.routers import documents, entities, ontology, grounding, enrichment, export, profiles, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    create_tables()
    yield


app = FastAPI(
    title="EIAS Entity Manager",
    description="Named-entity extraction, grounding, and knowledge management",
    version="0.1.0",
    lifespan=lifespan,
)

# --- Routers ---
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(entities.router, prefix="/api/entities", tags=["entities"])
app.include_router(ontology.router, prefix="/api/ontology", tags=["ontology"])
app.include_router(grounding.router, prefix="/api/grounding", tags=["grounding"])
app.include_router(enrichment.router, prefix="/api/enrichment", tags=["enrichment"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(profiles.router, prefix="/api/profiles", tags=["profiles"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])

# --- Static files ---
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    """Serve the SPA shell."""
    return FileResponse(
        str(static_dir / "index.html"),
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )
