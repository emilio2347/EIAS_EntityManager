"""Typed application settings stored in the AppSetting table."""

from __future__ import annotations

import importlib.util
import json
from typing import Any

import spacy
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import FUZZY_MATCH_THRESHOLD, SPACY_MODEL
from app.models import AppSetting

PIPELINE_SETTINGS_KEY = "pipeline.settings"


class PipelineSettings(BaseModel):
    """Runtime-tunable settings for extraction, coreference, and lookups."""

    spacy_model: str = Field(default=SPACY_MODEL)
    fuzzy_match_threshold: int = Field(default=FUZZY_MATCH_THRESHOLD, ge=0, le=100)
    coreference_enabled: bool = True
    grounding_search_limit: int = Field(default=5, ge=1, le=25)
    external_request_timeout: int = Field(default=15, ge=5, le=120)
    wikidata_type_filter_enabled: bool = True


def get_pipeline_settings(db: Session) -> PipelineSettings:
    setting = db.query(AppSetting).filter(AppSetting.key == PIPELINE_SETTINGS_KEY).first()
    if not setting:
        return PipelineSettings()
    try:
        data = json.loads(setting.value)
    except (TypeError, ValueError):
        return PipelineSettings()
    if not isinstance(data, dict):
        return PipelineSettings()
    return PipelineSettings(**data)


def set_pipeline_settings(db: Session, data: dict[str, Any]) -> PipelineSettings:
    current = get_pipeline_settings(db)
    merged = current.model_dump()
    merged.update(data)
    updated = PipelineSettings(**merged)

    setting = db.query(AppSetting).filter(AppSetting.key == PIPELINE_SETTINGS_KEY).first()
    value = updated.model_dump_json()
    if setting:
        setting.value = value
    else:
        db.add(AppSetting(key=PIPELINE_SETTINGS_KEY, value=value))
    db.commit()
    return updated


def pipeline_runtime_status(db: Session) -> dict[str, Any]:
    settings = get_pipeline_settings(db)
    model_installed = importlib.util.find_spec(settings.spacy_model) is not None
    coreferee_installed = importlib.util.find_spec("coreferee") is not None
    coreferee_pipe_available = False
    coreferee_error = ""

    if model_installed and coreferee_installed:
        try:
            nlp = spacy.load(settings.spacy_model)
            coreferee_pipe_available = "coreferee" in nlp.factory_names
        except Exception as exc:
            coreferee_error = str(exc)

    return {
        "settings": settings.model_dump(),
        "spacy_version": spacy.__version__,
        "spacy_model_installed": model_installed,
        "coreferee_installed": coreferee_installed,
        "coreferee_pipe_available": coreferee_pipe_available,
        "coreferee_error": coreferee_error,
    }
