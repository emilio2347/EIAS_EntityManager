"""Entity enrichment — fetch and import properties from Wikidata/DBpedia."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import Entity, EnrichmentProperty
from app.services import grounding_wikidata, grounding_dbpedia
from app.services.standard_triples import qid_from_wikidata_uri

logger = logging.getLogger(__name__)


async def get_available_properties(entity_id: str, db: Session) -> list[dict[str, Any]]:
    """Fetch available properties from external KGs for a grounded entity.

    Returns a combined list of properties from Wikidata and DBpedia.
    """
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        return []

    properties: list[dict[str, Any]] = []

    # Wikidata properties
    if entity.wikidata_uri:
        qid = qid_from_wikidata_uri(entity.wikidata_uri)
        try:
            if qid:
                wd_props = await grounding_wikidata.get_entity_properties(qid)
                properties.extend(wd_props)
        except Exception as e:
            logger.warning("Failed to fetch Wikidata properties for %s: %s", qid, e)

    # DBpedia properties
    if entity.dbpedia_uri:
        try:
            db_props = await grounding_dbpedia.get_entity_properties(entity.dbpedia_uri)
            properties.extend(db_props)
        except Exception as e:
            logger.warning("Failed to fetch DBpedia properties for %s: %s", entity.dbpedia_uri, e)

    # Filter out properties already imported
    existing = set()
    for ep in db.query(EnrichmentProperty).filter(EnrichmentProperty.entity_id == entity_id).all():
        existing.add((ep.property_uri, ep.value))

    properties = [p for p in properties if (p["property_uri"], p["value"]) not in existing]

    return properties


async def import_properties(
    entity_id: str,
    selected: list[dict[str, Any]],
    db: Session,
) -> list[dict[str, Any]]:
    """Import selected properties into the local database.

    Args:
        entity_id: The entity to enrich.
        selected: List of dicts with property_uri, property_name, value, source.
        db: Database session.

    Returns:
        List of imported property records.
    """
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        return []

    imported: list[dict[str, Any]] = []

    for prop in selected:
        # Skip if already exists
        exists = (
            db.query(EnrichmentProperty)
            .filter(
                EnrichmentProperty.entity_id == entity_id,
                EnrichmentProperty.property_uri == prop["property_uri"],
                EnrichmentProperty.value == prop["value"],
            )
            .first()
        )
        if exists:
            continue

        ep = EnrichmentProperty(
            entity_id=entity_id,
            property_name=prop.get("property_name", ""),
            property_uri=prop["property_uri"],
            value=prop["value"],
            source=prop.get("source", "unknown"),
        )
        db.add(ep)
        imported.append({
            "property_name": ep.property_name,
            "property_uri": ep.property_uri,
            "value": ep.value,
            "source": ep.source,
        })

    db.commit()
    return imported
