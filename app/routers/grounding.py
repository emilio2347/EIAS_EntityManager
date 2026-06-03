"""Entity grounding endpoints — search and confirm groundings."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Entity, EntityGroundingCandidate, EnrichmentProperty
from app.services.grounding_wikidata import search_wikidata
from app.services.grounding_worldcat import search_worldcat
from app.services.app_settings import get_pipeline_settings
from app.services.standard_triples import apply_grounding_derivatives

router = APIRouter()


def _candidate_uri(candidate: dict) -> str | None:
    uri = candidate.get("uri") or candidate.get("candidate_uri")
    return str(uri) if uri else None


def _filter_rejected_candidates(entity_id: str, authority: str, candidates: list[dict], db: Session) -> list[dict]:
    rejected = {
        row[0]
        for row in db.query(EntityGroundingCandidate.candidate_uri)
        .filter(
            EntityGroundingCandidate.entity_id == entity_id,
            EntityGroundingCandidate.authority == authority,
            EntityGroundingCandidate.review_status == "rejected",
        )
        .all()
    }
    return [candidate for candidate in candidates if _candidate_uri(candidate) not in rejected]


@router.post("/{entity_id}/search")
async def search_grounding(entity_id: str, db: Session = Depends(get_db)):
    """Search grounding candidates.

    Wikidata is the primary grounding target. WorldCat Entity candidates are
    shown only when they can be derived from Wikidata P10832.
    """
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    settings = get_pipeline_settings(db)
    wikidata_results = await search_wikidata(
        entity.canonical_name,
        entity.entity_type,
        limit=settings.grounding_search_limit,
        timeout=settings.external_request_timeout,
        type_filter_enabled=settings.wikidata_type_filter_enabled,
    )
    worldcat_results = await search_worldcat(
        entity.canonical_name,
        entity.entity_type,
        limit=settings.grounding_search_limit,
        timeout=settings.external_request_timeout,
        type_filter_enabled=settings.wikidata_type_filter_enabled,
    )
    wikidata_results = _filter_rejected_candidates(entity.id, "wikidata", wikidata_results, db)
    worldcat_results = _filter_rejected_candidates(entity.id, "worldcat", worldcat_results, db)

    return {
        "entity_id": entity.id,
        "entity_name": entity.canonical_name,
        "entity_type": entity.entity_type,
        "grounding": {
            "wikidata_uri": entity.wikidata_uri,
            "dbpedia_uri": entity.dbpedia_uri,
            "worldcat_uri": entity.worldcat_uri,
        },
        "candidates": {
            "wikidata": wikidata_results,
            "worldcat": worldcat_results,
        },
    }


class ConfirmGrounding(BaseModel):
    wikidata_uri: str | None = None
    dbpedia_uri: str | None = None
    worldcat_uri: str | None = None
    replace_enrichment: bool = True


class RejectGroundingCandidate(BaseModel):
    candidate_uri: str
    authority: str
    label: str | None = None
    score: float | None = None
    raw_candidate: dict | None = None


def _delete_entity_enrichment(entity_id: str, db: Session) -> int:
    """Remove enrichment rows that depend on the current grounding identity."""
    rows = (
        db.query(EnrichmentProperty)
        .filter(EnrichmentProperty.entity_id == entity_id)
        .all()
    )
    count = len(rows)
    for row in rows:
        db.delete(row)
    return count


@router.post("/{entity_id}/confirm")
async def confirm_grounding(
    entity_id: str,
    body: ConfirmGrounding,
    db: Session = Depends(get_db),
):
    """Confirm one or more grounding URIs for an entity."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    if not any([body.wikidata_uri, body.dbpedia_uri, body.worldcat_uri]):
        raise HTTPException(400, "At least one grounding URI is required")

    old_wikidata_uri = entity.wikidata_uri
    old_dbpedia_uri = entity.dbpedia_uri
    old_worldcat_uri = entity.worldcat_uri

    grounding_changed = (
        (body.wikidata_uri is not None and body.wikidata_uri != old_wikidata_uri)
        or (body.dbpedia_uri is not None and body.dbpedia_uri != old_dbpedia_uri)
        or (body.worldcat_uri is not None and body.worldcat_uri != old_worldcat_uri)
    )

    removed_enrichment_count = 0
    if body.replace_enrichment and grounding_changed:
        removed_enrichment_count = _delete_entity_enrichment(entity.id, db)

    if body.wikidata_uri is not None:
        entity.wikidata_uri = body.wikidata_uri
        if body.wikidata_uri != old_wikidata_uri:
            entity.dbpedia_uri = None
            entity.worldcat_uri = None
            entity.image_url = None
    if body.dbpedia_uri is not None:
        entity.dbpedia_uri = body.dbpedia_uri
    if body.worldcat_uri is not None:
        entity.worldcat_uri = body.worldcat_uri

    db.commit()
    derivatives = await apply_grounding_derivatives(entity, db)
    db.refresh(entity)

    return {
        "status": "grounded",
        "entity_id": entity.id,
        "wikidata_uri": entity.wikidata_uri,
        "dbpedia_uri": entity.dbpedia_uri,
        "worldcat_uri": entity.worldcat_uri,
        "image_url": entity.image_url,
        "derived_uris": derivatives["derived_uris"],
        "standard_triples_imported": len(derivatives["imported"]),
        "removed_enrichment_count": removed_enrichment_count,
    }


@router.post("/{entity_id}/reject")
async def reject_grounding_candidate(
    entity_id: str,
    body: RejectGroundingCandidate,
    db: Session = Depends(get_db),
):
    """Record a rejected grounding candidate so it is not suggested again."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    candidate_uri = body.candidate_uri.strip()
    authority = body.authority.strip().lower()
    if not candidate_uri or not authority:
        raise HTTPException(400, "candidate_uri and authority are required")

    existing = (
        db.query(EntityGroundingCandidate)
        .filter(
            EntityGroundingCandidate.entity_id == entity_id,
            EntityGroundingCandidate.candidate_uri == candidate_uri,
        )
        .first()
    )
    if existing:
        existing.review_status = "rejected"
        existing.authority = authority
        existing.label = body.label
        existing.score = body.score
        existing.raw_candidate = body.raw_candidate and json.dumps(body.raw_candidate, ensure_ascii=False)
    else:
        db.add(
            EntityGroundingCandidate(
                entity_id=entity_id,
                candidate_uri=candidate_uri,
                authority=authority,
                label=body.label,
                score=body.score,
                review_status="rejected",
                raw_candidate=body.raw_candidate and json.dumps(body.raw_candidate, ensure_ascii=False),
            )
        )
    db.commit()
    return {"status": "rejected", "entity_id": entity_id, "candidate_uri": candidate_uri}


@router.delete("/{entity_id}")
async def clear_grounding(entity_id: str, db: Session = Depends(get_db)):
    """Remove grounding URIs and enrichment derived from the grounding."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    removed_enrichment_count = _delete_entity_enrichment(entity.id, db)
    entity.wikidata_uri = None
    entity.dbpedia_uri = None
    entity.worldcat_uri = None
    entity.image_url = None
    db.commit()
    db.refresh(entity)

    return {
        "status": "ungrounded",
        "entity_id": entity.id,
        "wikidata_uri": entity.wikidata_uri,
        "dbpedia_uri": entity.dbpedia_uri,
        "worldcat_uri": entity.worldcat_uri,
        "image_url": entity.image_url,
        "removed_enrichment_count": removed_enrichment_count,
    }


@router.post("/bulk")
async def bulk_ground(db: Session = Depends(get_db)):
    """Auto-ground all ungrounded entities.

    For each ungrounded entity, picks the top Wikidata candidate (if any).
    Returns a summary of what was grounded.
    """
    ungrounded = (
        db.query(Entity)
        .filter(
            Entity.wikidata_uri.is_(None),
        )
        .all()
    )

    results = []
    settings = get_pipeline_settings(db)
    for entity in ungrounded:
        try:
            wd = await search_wikidata(
                entity.canonical_name,
                entity.entity_type,
                limit=1,
                timeout=settings.external_request_timeout,
                type_filter_enabled=settings.wikidata_type_filter_enabled,
            )
            if wd:
                entity.wikidata_uri = wd[0]["uri"]
                db.commit()
                await apply_grounding_derivatives(entity, db)
                db.refresh(entity)

            results.append({
                "entity_id": entity.id,
                "canonical_name": entity.canonical_name,
                "wikidata_uri": entity.wikidata_uri,
                "dbpedia_uri": entity.dbpedia_uri,
                "worldcat_uri": entity.worldcat_uri,
                "image_url": entity.image_url,
            })
        except Exception:
            pass

    db.commit()

    return {
        "grounded_count": len(results),
        "results": results,
    }
