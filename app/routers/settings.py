"""Application settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.standard_triples import (
    STANDARD_TRIPLE_GROUPS,
    get_enabled_standard_property_ids,
    set_enabled_standard_property_ids,
)
from app.services.app_settings import (
    pipeline_runtime_status,
    set_pipeline_settings,
)

router = APIRouter()


@router.get("/standard-triples")
def get_standard_triples_settings(db: Session = Depends(get_db)):
    """List selectable standard triples and the current enabled choices."""
    return {
        "groups": STANDARD_TRIPLE_GROUPS,
        "enabled_property_ids": get_enabled_standard_property_ids(db),
    }


class StandardTriplesUpdate(BaseModel):
    enabled_property_ids: list[str]


@router.put("/standard-triples")
def update_standard_triples_settings(
    body: StandardTriplesUpdate,
    db: Session = Depends(get_db),
):
    """Update which Wikidata-derived triples are auto-imported after grounding."""
    return {
        "enabled_property_ids": set_enabled_standard_property_ids(
            db,
            body.enabled_property_ids,
        ),
    }


@router.get("/pipeline")
def get_pipeline_settings_endpoint(db: Session = Depends(get_db)):
    """Get tunable pipeline settings and runtime dependency status."""
    return pipeline_runtime_status(db)


class PipelineSettingsUpdate(BaseModel):
    spacy_model: str | None = None
    fuzzy_match_threshold: int | None = None
    coreference_enabled: bool | None = None
    grounding_search_limit: int | None = None
    external_request_timeout: int | None = None
    wikidata_type_filter_enabled: bool | None = None


@router.put("/pipeline")
def update_pipeline_settings(
    body: PipelineSettingsUpdate,
    db: Session = Depends(get_db),
):
    """Persist runtime-tunable pipeline settings."""
    data = body.model_dump(exclude_none=True)
    updated = set_pipeline_settings(db, data)
    return {
        "settings": updated.model_dump(),
        "status": pipeline_runtime_status(db),
    }
