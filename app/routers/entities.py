"""Entity browsing, searching, merging, and deletion endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Entity, Mention, EnrichmentProperty, CoreferenceChain, CoreferenceMember

router = APIRouter()


def _load_alt_labels(entity: Entity) -> list[str]:
    """Decode the alternative_labels JSON column into a clean list."""
    raw = entity.alternative_labels or "[]"
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data if x]
    except (ValueError, TypeError):
        pass
    return []


def _store_alt_labels(entity: Entity, labels: list[str]) -> None:
    """Encode a list of alt-labels back into the entity, deduped and clean."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for lab in labels:
        if not lab:
            continue
        s = str(lab).strip()
        if not s or s == entity.canonical_name or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    entity.alternative_labels = json.dumps(cleaned, ensure_ascii=False)


def _mention_context_snippet(mention: Mention, radius: int = 80) -> str:
    """Return document context around a mention with the surface form bracketed."""
    text = mention.document.content_text if mention.document else ""
    if not text:
        return mention.sentence or mention.surface_form

    start = max(0, mention.start_char - radius)
    end = min(len(text), mention.end_char + radius)
    prefix = text[start:mention.start_char].replace("\n", " ").strip()
    suffix = text[mention.end_char:end].replace("\n", " ").strip()
    surface = text[mention.start_char:mention.end_char] or mention.surface_form

    snippet = f"{prefix} [{surface}] {suffix}".strip()
    if start > 0:
        snippet = f"... {snippet}"
    if end < len(text):
        snippet = f"{snippet} ..."
    return " ".join(snippet.split())


@router.get("")
def list_entities(
    q: str = Query("", description="Search by name"),
    entity_type: str = Query("", description="Filter by type"),
    grounded: str = Query("", description="Filter: 'yes', 'no', or ''"),
    ontology_linked: str = Query("", description="Filter ontology individual link: 'yes', 'no', or ''"),
    document_id: str = Query("", description="Restrict to entities mentioned in this document"),
    profile_id: str = Query("", description="Restrict to entities in a profile"),
    db: Session = Depends(get_db),
):
    """List/search entities."""
    query = db.query(Entity)

    if q:
        query = query.filter(Entity.canonical_name.ilike(f"%{q}%"))
    if entity_type:
        query = query.filter(Entity.entity_type == entity_type)
    if profile_id:
        query = query.filter(Entity.profile_id == profile_id)
    if grounded == "yes":
        query = query.filter(
            (Entity.wikidata_uri.isnot(None))
            | (Entity.dbpedia_uri.isnot(None))
            | (Entity.worldcat_uri.isnot(None))
        )
    elif grounded == "no":
        query = query.filter(
            Entity.wikidata_uri.is_(None),
            Entity.dbpedia_uri.is_(None),
            Entity.worldcat_uri.is_(None),
        )
    if ontology_linked == "yes":
        query = query.filter(Entity.ontology_individual_uri.isnot(None))
    elif ontology_linked == "no":
        query = query.filter(Entity.ontology_individual_uri.is_(None))
    if document_id:
        query = query.join(Mention, Mention.entity_id == Entity.id).filter(
            Mention.document_id == document_id
        ).distinct()

    entities = query.order_by(Entity.canonical_name).all()

    # If filtering by document, count only mentions in that document; otherwise total.
    def _mention_count(entity_id: str) -> int:
        q_m = db.query(Mention).filter(Mention.entity_id == entity_id)
        if document_id:
            q_m = q_m.filter(Mention.document_id == document_id)
        return q_m.count()

    return [
        {
            "id": e.id,
            "profile_id": e.profile_id,
            "canonical_name": e.canonical_name,
            "entity_type": e.entity_type,
            "alternative_labels": _load_alt_labels(e),
            "ontology_class_uri": e.ontology_class_uri,
            "ontology_individual_uri": e.ontology_individual_uri,
            "wikidata_uri": e.wikidata_uri,
            "dbpedia_uri": e.dbpedia_uri,
            "worldcat_uri": e.worldcat_uri,
            "image_url": e.image_url,
            "mention_count": _mention_count(e.id),
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entities
    ]


@router.get("/{entity_id}")
def get_entity(entity_id: str, db: Session = Depends(get_db)):
    """Get full entity detail: mentions, coreferences, enrichment."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    mentions = db.query(Mention).filter(Mention.entity_id == entity_id).all()
    enrichments = db.query(EnrichmentProperty).filter(
        EnrichmentProperty.entity_id == entity_id
    ).all()
    coref_chains = db.query(CoreferenceChain).filter(
        CoreferenceChain.entity_id == entity_id
    ).all()

    chains_data = []
    for chain in coref_chains:
        members = db.query(CoreferenceMember).filter(
            CoreferenceMember.chain_id == chain.id
        ).all()
        chains_data.append({
            "chain_id": chain.id,
            "chain_index": chain.chain_index,
            "document_id": chain.document_id,
            "members": [
                {
                    "surface_form": m.surface_form,
                    "start_char": m.start_char,
                    "end_char": m.end_char,
                }
                for m in members
            ],
        })

    return {
        "id": entity.id,
        "profile_id": entity.profile_id,
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type,
        "alternative_labels": _load_alt_labels(entity),
        "ontology_class_uri": entity.ontology_class_uri,
        "ontology_individual_uri": entity.ontology_individual_uri,
        "wikidata_uri": entity.wikidata_uri,
        "dbpedia_uri": entity.dbpedia_uri,
        "worldcat_uri": entity.worldcat_uri,
        "image_url": entity.image_url,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
        "mentions": [
            {
                "id": m.id,
                "document_id": m.document_id,
                "document_filename": m.document.filename if m.document else "",
                "surface_form": m.surface_form,
                "start_char": m.start_char,
                "end_char": m.end_char,
                "sentence": m.sentence,
                "context_snippet": _mention_context_snippet(m),
            }
            for m in mentions
        ],
        "coreference_chains": chains_data,
        "enrichment": [
            {
                "id": ep.id,
                "property_name": ep.property_name,
                "property_uri": ep.property_uri,
                "value": ep.value,
                "source": ep.source,
                "imported_at": ep.imported_at.isoformat() if ep.imported_at else None,
            }
            for ep in enrichments
        ],
    }


class UpdateTypeRequest(BaseModel):
    entity_type: str


@router.patch("/{entity_id}/type")
def update_entity_type(entity_id: str, body: UpdateTypeRequest, db: Session = Depends(get_db)):
    """Update the NER label (entity_type) of an entity."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    old_type = entity.entity_type
    entity.entity_type = body.entity_type

    # Re-map ontology class if a mapping exists for the new type
    from app.models import OntologyMapping
    mapping = db.query(OntologyMapping).filter(
        OntologyMapping.spacy_label == body.entity_type
    ).first()
    if mapping:
        entity.ontology_class_uri = mapping.ontology_class_uri
    else:
        entity.ontology_class_uri = None

    db.commit()

    return {
        "status": "updated",
        "entity_id": entity.id,
        "old_type": old_type,
        "new_type": entity.entity_type,
        "ontology_class_uri": entity.ontology_class_uri,
    }


class MergeRequest(BaseModel):
    target_entity_id: str


@router.post("/{entity_id}/merge")
def merge_entities(entity_id: str, body: MergeRequest, db: Session = Depends(get_db)):
    """Merge entity_id INTO target_entity_id.

    All mentions, coreference chains, and enrichment are transferred.
    The source entity's canonical_name and its alternative labels become
    alternative labels on the target. The source entity is then deleted.
    """
    if entity_id == body.target_entity_id:
        raise HTTPException(400, "Cannot merge an entity into itself")

    source = db.query(Entity).filter(Entity.id == entity_id).first()
    target = db.query(Entity).filter(Entity.id == body.target_entity_id).first()

    if not source:
        raise HTTPException(404, "Source entity not found")
    if not target:
        raise HTTPException(404, "Target entity not found")
    if source.profile_id != target.profile_id:
        raise HTTPException(400, "Cannot merge entities from different profiles")

    # Merge alternative labels: target keeps its preferred name; source name + its
    # alt labels become alt labels on target.
    target_alts = _load_alt_labels(target)
    source_alts = _load_alt_labels(source)
    merged_alts = list(target_alts)
    for label in [source.canonical_name, *source_alts]:
        if label and label != target.canonical_name and label not in merged_alts:
            merged_alts.append(label)
    _store_alt_labels(target, merged_alts)

    # Transfer mentions
    db.query(Mention).filter(Mention.entity_id == entity_id).update(
        {"entity_id": body.target_entity_id}
    )

    # Transfer coreference chains
    db.query(CoreferenceChain).filter(CoreferenceChain.entity_id == entity_id).update(
        {"entity_id": body.target_entity_id}
    )

    # Transfer enrichment (skip duplicates)
    for ep in db.query(EnrichmentProperty).filter(EnrichmentProperty.entity_id == entity_id).all():
        existing = (
            db.query(EnrichmentProperty)
            .filter(
                EnrichmentProperty.entity_id == body.target_entity_id,
                EnrichmentProperty.property_uri == ep.property_uri,
                EnrichmentProperty.value == ep.value,
            )
            .first()
        )
        if not existing:
            ep.entity_id = body.target_entity_id
        else:
            db.delete(ep)

    # Copy grounding URIs if target lacks them
    if not target.wikidata_uri and source.wikidata_uri:
        target.wikidata_uri = source.wikidata_uri
    if not target.dbpedia_uri and source.dbpedia_uri:
        target.dbpedia_uri = source.dbpedia_uri
    if not target.worldcat_uri and source.worldcat_uri:
        target.worldcat_uri = source.worldcat_uri
    if not target.ontology_individual_uri and source.ontology_individual_uri:
        target.ontology_individual_uri = source.ontology_individual_uri

    db.delete(source)
    db.commit()

    return {
        "status": "merged",
        "target_entity_id": body.target_entity_id,
        "alternative_labels": _load_alt_labels(target),
    }


class PrefLabelRequest(BaseModel):
    label: str


@router.patch("/{entity_id}/preflabel")
def set_preferred_label(entity_id: str, body: PrefLabelRequest, db: Session = Depends(get_db)):
    """Promote a label to be the canonical (preferred) name.

    The previous canonical_name is moved into alternative_labels. The new label
    is removed from alternative_labels if it was present there.
    """
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    new_label = body.label.strip()
    if not new_label:
        raise HTTPException(400, "Label cannot be empty")
    if new_label == entity.canonical_name:
        return {
            "status": "unchanged",
            "canonical_name": entity.canonical_name,
            "alternative_labels": _load_alt_labels(entity),
        }

    alts = _load_alt_labels(entity)
    alts = [l for l in alts if l != new_label]
    if entity.canonical_name and entity.canonical_name not in alts:
        alts.append(entity.canonical_name)

    entity.canonical_name = new_label
    _store_alt_labels(entity, alts)

    db.commit()
    return {
        "status": "updated",
        "canonical_name": entity.canonical_name,
        "alternative_labels": _load_alt_labels(entity),
    }


class AltLabelsRequest(BaseModel):
    labels: list[str]


@router.patch("/{entity_id}/altlabels")
def set_alt_labels(entity_id: str, body: AltLabelsRequest, db: Session = Depends(get_db)):
    """Replace the alternative labels list for an entity."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    _store_alt_labels(entity, body.labels)
    db.commit()
    return {
        "status": "updated",
        "alternative_labels": _load_alt_labels(entity),
    }


class IndividualRequest(BaseModel):
    ontology_individual_uri: str | None


@router.patch("/{entity_id}/individual")
def set_individual(entity_id: str, body: IndividualRequest, db: Session = Depends(get_db)):
    """Link/unlink an entity to an ontology Particular (NamedIndividual)."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    uri = body.ontology_individual_uri
    entity.ontology_individual_uri = uri.strip() if uri and uri.strip() else None
    db.commit()
    return {
        "status": "updated",
        "ontology_individual_uri": entity.ontology_individual_uri,
    }


@router.delete("")
def delete_all_entities(
    profile_id: str = Query("", description="Restrict deletion to one profile"),
    db: Session = Depends(get_db),
):
    """Delete every entity (and all dependent mentions, coref chains, enrichment).

    The cascade is handled per-entity via SQLAlchemy relationships rather than
    a bulk DELETE so that the cascade configured on Entity is honored.
    """
    query = db.query(Entity)
    if profile_id:
        query = query.filter(Entity.profile_id == profile_id)
    entities = query.all()
    count = len(entities)
    for ent in entities:
        db.delete(ent)
    db.commit()
    return {"status": "deleted", "deleted_count": count}


@router.delete("/{entity_id}")
def delete_entity(entity_id: str, db: Session = Depends(get_db)):
    """Delete an entity and all its mentions/enrichment."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")

    db.delete(entity)
    db.commit()
    return {"status": "deleted", "entity_id": entity_id}
