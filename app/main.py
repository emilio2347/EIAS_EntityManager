"""EIAS suite — FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import assert_runtime_database_ready
from app.routers import (
    corpus,
    database_view,
    document_manager,
    enrichment,
    entities,
    export,
    grounding,
    ontology,
    profiles,
    settings,
    topic_manager,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    assert_runtime_database_ready()
    yield


app = FastAPI(
    title="EIAS",
    description="Document, entity, and topic management for the EIAS corpus",
    version="0.1.0",
    lifespan=lifespan,
)

# --- Routers ---
app.include_router(document_manager.router, prefix="/api/document-manager", tags=["document-manager"])
app.include_router(corpus.router, prefix="/api/corpus", tags=["corpus"])
app.include_router(topic_manager.router, prefix="/api/topic-manager", tags=["topic-manager"])
app.include_router(database_view.router, prefix="/api/database", tags=["database"])
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
