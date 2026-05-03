"""Entity grounding endpoints — search and confirm groundings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Entity
from app.services.grounding_wikidata import search_wikidata
from app.services.grounding_dbpedia import search_dbpedia
from app.services.grounding_worldcat import search_worldcat

router = APIRouter()


@router.post("/{entity_id}/search")
async def search_grounding(entity_id: str, db: Session = Depends(get_db)):
    """Search all grounding sources for candidate matches.

    Returns candidates from Wikidata, DBpedia, and WorldCat.
    """
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    # Query all sources in parallel-ish fashion
    wikidata_results = await search_wikidata(entity.canonical_name, entity.entity_type)
    dbpedia_results = await search_dbpedia(entity.canonical_name, entity.entity_type)
    worldcat_results = await search_worldcat(entity.canonical_name)

    return {
        "entity_id": entity.id,
        "entity_name": entity.canonical_name,
        "entity_type": entity.entity_type,
        "candidates": {
            "wikidata": wikidata_results,
            "dbpedia": dbpedia_results,
            "worldcat": worldcat_results,
        },
    }


class ConfirmGrounding(BaseModel):
    wikidata_uri: str | None = None
    dbpedia_uri: str | None = None
    worldcat_uri: str | None = None


@router.post("/{entity_id}/confirm")
def confirm_grounding(
    entity_id: str,
    body: ConfirmGrounding,
    db: Session = Depends(get_db),
):
    """Confirm one or more grounding URIs for an entity."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    if body.wikidata_uri is not None:
        entity.wikidata_uri = body.wikidata_uri
    if body.dbpedia_uri is not None:
        entity.dbpedia_uri = body.dbpedia_uri
    if body.worldcat_uri is not None:
        entity.worldcat_uri = body.worldcat_uri

    db.commit()

    return {
        "status": "grounded",
        "entity_id": entity.id,
        "wikidata_uri": entity.wikidata_uri,
        "dbpedia_uri": entity.dbpedia_uri,
        "worldcat_uri": entity.worldcat_uri,
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
            Entity.dbpedia_uri.is_(None),
        )
        .all()
    )

    results = []
    for entity in ungrounded:
        try:
            wd = await search_wikidata(entity.canonical_name, entity.entity_type, limit=1)
            if wd:
                entity.wikidata_uri = wd[0]["uri"]

            db_results = await search_dbpedia(entity.canonical_name, entity.entity_type, limit=1)
            if db_results:
                entity.dbpedia_uri = db_results[0]["uri"]

            results.append({
                "entity_id": entity.id,
                "canonical_name": entity.canonical_name,
                "wikidata_uri": entity.wikidata_uri,
                "dbpedia_uri": entity.dbpedia_uri,
            })
        except Exception:
            pass

    db.commit()

    return {
        "grounded_count": len(results),
        "results": results,
    }
