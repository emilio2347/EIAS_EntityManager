"""Helpers for shared corpus objects and annotation provenance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import TEXT_VERSION_DIR
from app.models import (
    Article,
    EntityExtractionProfile,
    ProcessingRun,
    SpanAnnotation,
    TextVersion,
    ensure_article_profile,
    get_or_create_component,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_text_version_file(text_version_id: str, text: str) -> str:
    TEXT_VERSION_DIR.mkdir(parents=True, exist_ok=True)
    path = TEXT_VERSION_DIR / f"{text_version_id}.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def create_article_with_text(
    db: Session,
    *,
    filename: str,
    filetype: str,
    content_text: str,
    profile_id: str | None,
    legacy_document_id: str | None = None,
    created_at: datetime | None = None,
    article_id: str | None = None,
    text_version_id: str | None = None,
) -> Article:
    article = Article(
        id=article_id,
        filename=filename,
        filetype=filetype,
        legacy_document_id=legacy_document_id,
        uploaded_at=created_at or datetime.now(timezone.utc),
    )
    db.add(article)
    db.flush()

    text_version = TextVersion(
        id=text_version_id,
        article_id=article.id,
        raw_text=content_text,
        normalized_text=content_text,
        sha256_raw_text=_sha256(content_text),
        sha256_normalized_text=_sha256(content_text),
        normalization_method="original",
        legacy_document_id=legacy_document_id,
        created_at=article.uploaded_at,
    )
    db.add(text_version)
    db.flush()
    text_version.raw_text_path = write_text_version_file(text_version.id, content_text)
    text_version.normalized_text_path = text_version.raw_text_path
    article.current_text_version_id = text_version.id
    ensure_article_profile(db, article, profile_id)
    return article


def create_processing_run(
    db: Session,
    *,
    text_version_id: str,
    profile_id: str | None,
    tool_name: str,
    model_name: str | None,
    model_version: str | None,
    parameters: dict | None = None,
    status: str = "completed",
    run_id: str | None = None,
    component_slug: str = "entity_manager",
    component_name: str = "EIAS Entity Manager",
) -> ProcessingRun:
    component = get_or_create_component(db, slug=component_slug, name=component_name)
    now = datetime.now(timezone.utc)
    run = ProcessingRun(
        id=run_id,
        component_id=component.id,
        text_version_id=text_version_id,
        profile_id=profile_id,
        tool_name=tool_name,
        model_name=model_name,
        model_version=model_version,
        parameters_json=json.dumps(parameters or {}, ensure_ascii=False),
        status=status,
        started_at=now,
        completed_at=now if status == "completed" else None,
        created_at=now,
    )
    db.add(run)
    db.flush()
    return run


def create_span_annotation(
    db: Session,
    *,
    processing_run_id: str,
    text_version_id: str,
    annotation_type: str,
    start_char: int,
    end_char: int,
    exact_text: str,
    motivation: str,
    body: dict | None = None,
    confidence: float | None = None,
    legacy_mention_id: str | None = None,
    annotation_id: str | None = None,
) -> SpanAnnotation:
    annotation = SpanAnnotation(
        id=annotation_id,
        processing_run_id=processing_run_id,
        text_version_id=text_version_id,
        annotation_type=annotation_type,
        start_char=start_char,
        end_char=end_char,
        exact_text=exact_text,
        motivation=motivation,
        body_json=json.dumps(body or {}, ensure_ascii=False),
        confidence=confidence,
        legacy_mention_id=legacy_mention_id,
    )
    db.add(annotation)
    db.flush()
    return annotation


def current_text_version_or_404(article: Article) -> TextVersion:
    if not article.current_text_version:
        raise ValueError(f"Article {article.id} has no current text version")
    return article.current_text_version


def default_profile(db: Session) -> EntityExtractionProfile | None:
    return db.query(EntityExtractionProfile).filter(EntityExtractionProfile.is_default.is_(True)).first()
