"""Entity enrichment endpoints — browse and import external properties."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Entity, EnrichmentProperty
from app.services.enrichment import get_available_properties, import_properties

router = APIRouter()


@router.get("/{entity_id}/available")
async def available_properties(entity_id: str, db: Session = Depends(get_db)):
    """Get available properties from Wikidata/DBpedia for a grounded entity."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    if not entity.wikidata_uri and not entity.dbpedia_uri:
        raise HTTPException(400, "Entity must be grounded first (needs Wikidata or DBpedia URI)")

    properties = await get_available_properties(entity_id, db)

    return {
        "entity_id": entity.id,
        "entity_name": entity.canonical_name,
        "available_properties": properties,
    }


class ImportRequest(BaseModel):
    properties: list[dict]


@router.post("/{entity_id}/import")
async def import_enrichment(
    entity_id: str,
    body: ImportRequest,
    db: Session = Depends(get_db),
):
    """Import selected properties into the local entity database."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    imported = await import_properties(entity_id, body.properties, db)

    return {
        "entity_id": entity.id,
        "imported_count": len(imported),
        "imported": imported,
    }


@router.delete("/{entity_id}/properties/{property_id}")
def delete_enrichment_property(
    entity_id: str,
    property_id: str,
    db: Session = Depends(get_db),
):
    """Delete one imported enrichment property for an entity."""
    prop = (
        db.query(EnrichmentProperty)
        .filter(
            EnrichmentProperty.id == property_id,
            EnrichmentProperty.entity_id == entity_id,
        )
        .first()
    )
    if not prop:
        raise HTTPException(404, "Enrichment property not found")

    db.delete(prop)
    db.commit()
    return {"status": "deleted", "property_id": property_id}
