"""Entity browsing, searching, merging, and deletion endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Entity,
    EntityMention,
    EntityReconciliationEvent,
    Mention,
    EnrichmentProperty,
    CoreferenceChain,
    CoreferenceMember,
    SpanAnnotation,
    ensure_entity_aliases,
)

router = APIRouter()
ALLOWED_REVIEW_STATUSES = {
    "machine_generated",
    "needs_review",
    "accepted",
    "rejected",
    "manually_created",
    "superseded",
}


def _clean_review_status(value: str) -> str:
    status = (value or "").strip().lower()
    if status not in ALLOWED_REVIEW_STATUSES:
        raise HTTPException(400, f"review_status must be one of: {', '.join(sorted(ALLOWED_REVIEW_STATUSES))}")
    return status


def _load_alt_labels(entity: Entity) -> list[str]:
    """Decode the alternative_labels JSON column into a clean list."""
    return [alias.alias for alias in entity.aliases if alias.alias]


def _store_alt_labels(entity: Entity, labels: list[str]) -> None:
    """Encode a list of alt-labels back into the entity, deduped and clean."""
    ensure_entity_aliases(entity, labels)


def _mention_sentence(mention: Mention) -> str | None:
    raw = mention.sentence
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("sentence")
    except (ValueError, TypeError):
        pass
    return raw


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


def _group_mentions_by_article(mentions: list[Mention]) -> dict[str, list[Mention]]:
    grouped: dict[str, list[Mention]] = {}
    for mention in mentions:
        article_id = mention.document_id
        grouped.setdefault(article_id, []).append(mention)
    return grouped


@router.get("")
def list_entities(
    q: str = Query("", description="Search by name"),
    entity_type: str = Query("", description="Filter by type"),
    grounded: str = Query("", description="Legacy grounding filter: 'yes', 'no', or ''"),
    grounding_status: str = Query("", description="Filter: 'grounded', 'ungrounded', or ''"),
    ontology_linked: str = Query("", description="Filter ontology individual link: 'yes', 'no', or ''"),
    ontology_class_uri: str = Query("", description="Restrict to ontology class URI"),
    article_id: str = Query("", description="Restrict to entities mentioned in this article"),
    text_version_id: str = Query("", description="Restrict to entities mentioned in this text version"),
    document_id: str = Query("", description="Restrict to entities mentioned in this document"),
    profile_id: str = Query("", description="Deprecated; ignored"),
    db: Session = Depends(get_db),
):
    """List/search entities."""
    query = db.query(Entity)

    if q:
        query = query.filter(Entity.canonical_name.ilike(f"%{q}%"))
    if entity_type:
        query = query.filter(Entity.entity_type == entity_type)
    resolved_grounding_status = grounding_status or ({"yes": "grounded", "no": "ungrounded"}.get(grounded, ""))
    if resolved_grounding_status == "grounded":
        query = query.filter(
            (Entity.wikidata_uri.isnot(None))
            | (Entity.dbpedia_uri.isnot(None))
            | (Entity.worldcat_uri.isnot(None))
        )
    elif resolved_grounding_status == "ungrounded":
        query = query.filter(
            Entity.wikidata_uri.is_(None),
            Entity.dbpedia_uri.is_(None),
            Entity.worldcat_uri.is_(None),
        )
    if ontology_class_uri:
        query = query.filter(Entity.ontology_class_uri == ontology_class_uri)
    if ontology_linked == "yes":
        query = query.filter(Entity.ontology_individual_uri.isnot(None))
    elif ontology_linked == "no":
        query = query.filter(Entity.ontology_individual_uri.is_(None))
    corpus_article_id = article_id or document_id
    if corpus_article_id:
        query = query.join(Mention, Mention.entity_id == Entity.id).filter(
            Mention.document_id == corpus_article_id
        ).distinct()
    if text_version_id:
        query = (
            query.join(EntityMention, EntityMention.entity_id == Entity.id)
            .join(SpanAnnotation, SpanAnnotation.id == EntityMention.annotation_id)
            .filter(SpanAnnotation.text_version_id == text_version_id)
            .distinct()
        )

    entities = query.order_by(Entity.canonical_name).all()

    # If filtering by document, count only mentions in that document; otherwise total.
    def _mention_count(entity_id: str) -> int:
        q_m = db.query(Mention).filter(Mention.entity_id == entity_id)
        if corpus_article_id:
            q_m = q_m.filter(Mention.document_id == corpus_article_id)
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
            "review_status": e.review_status,
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
        "review_status": entity.review_status,
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
                "annotation_id": m.annotation_id,
                "document_id": m.document_id,
                "document_filename": m.document.filename if m.document else "",
                "text_version_id": m.annotation.text_version_id if m.annotation else None,
                "surface_form": m.surface_form,
                "start_char": m.start_char,
                "end_char": m.end_char,
                "sentence": _mention_sentence(m),
                "context_snippet": _mention_context_snippet(m),
                "review_status": m.review_status,
            }
            for m in mentions
        ],
        "mention_contexts_by_article": [
            {
                "article_id": article_id,
                "filename": group[0].document.filename if group[0].document else "",
                "text_version_id": group[0].annotation.text_version_id if group[0].annotation else None,
                "mention_count": len(group),
                "mentions": [
                    {
                        "id": mention.id,
                        "surface_form": mention.surface_form,
                        "start_char": mention.start_char,
                        "end_char": mention.end_char,
                        "context_snippet": _mention_context_snippet(mention),
                        "review_status": mention.review_status,
                    }
                    for mention in group
                ],
            }
            for article_id, group in _group_mentions_by_article(mentions).items()
        ],
        "coreference_chains": chains_data,
        "enrichment": [
            {
                "id": ep.id,
                "property_name": ep.property_name,
                "property_uri": ep.property_uri,
                "value": ep.value,
                "source": ep.source,
                "review_status": ep.review_status,
                "imported_at": ep.imported_at.isoformat() if ep.imported_at else None,
            }
            for ep in enrichments
        ],
    }


class UpdateTypeRequest(BaseModel):
    entity_type: str


class ReviewStatusRequest(BaseModel):
    review_status: str


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


@router.patch("/{entity_id}/review-status")
def update_entity_review_status(
    entity_id: str,
    body: ReviewStatusRequest,
    db: Session = Depends(get_db),
):
    """Update curation review status for a canonical entity."""
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")
    entity.review_status = _clean_review_status(body.review_status)
    db.commit()
    return {"status": "updated", "entity_id": entity.id, "review_status": entity.review_status}


@router.patch("/{entity_id}/mentions/{mention_id}/review-status")
def update_mention_review_status(
    entity_id: str,
    mention_id: str,
    body: ReviewStatusRequest,
    db: Session = Depends(get_db),
):
    """Update curation review status for one entity mention."""
    mention = (
        db.query(Mention)
        .filter(Mention.id == mention_id, Mention.entity_id == entity_id)
        .first()
    )
    if not mention:
        raise HTTPException(404, "Mention not found")
    mention.review_status = _clean_review_status(body.review_status)
    db.commit()
    return {"status": "updated", "mention_id": mention.id, "review_status": mention.review_status}


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
    transferred_mentions = db.query(Mention).filter(Mention.entity_id == entity_id).count()
    db.query(Mention).filter(Mention.entity_id == entity_id).update(
        {"entity_id": body.target_entity_id}
    )

    # Transfer coreference chains
    db.query(CoreferenceChain).filter(CoreferenceChain.entity_id == entity_id).update(
        {"entity_id": body.target_entity_id}
    )

    # Transfer enrichment (skip duplicates)
    transferred_enrichments = 0
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
            transferred_enrichments += 1
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

    source_aliases = _load_alt_labels(source)
    reconciliation_event = EntityReconciliationEvent(
        source_entity_id=source.id,
        target_entity_id=target.id,
        action="merge",
        actor="entity_manager",
        transferred_mentions=transferred_mentions,
        transferred_aliases=len([source.canonical_name, *source_aliases]),
        transferred_enrichments=transferred_enrichments,
        details_json=json.dumps(
            {
                "source_canonical_name": source.canonical_name,
                "target_canonical_name": target.canonical_name,
                "source_aliases": source_aliases,
            },
            ensure_ascii=False,
        ),
    )
    db.add(reconciliation_event)
    db.flush()
    reconciliation_event.source_entity_id = None
    db.delete(source)
    db.commit()

    return {
        "status": "merged",
        "target_entity_id": body.target_entity_id,
        "reconciliation_event_id": reconciliation_event.id,
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
    profile_id: str = Query("", description="Deprecated; ignored"),
    db: Session = Depends(get_db),
):
    """Delete every entity (and all dependent mentions, coref chains, enrichment).

    The cascade is handled per-entity via SQLAlchemy relationships rather than
    a bulk DELETE so that the cascade configured on Entity is honored.
    """
    query = db.query(Entity)
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
