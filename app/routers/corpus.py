"""Read-only corpus context endpoints for EntityManager."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Article,
    CoreferenceChain,
    CoreferenceMember,
    Entity,
    EntityExtractionArticle,
    EntityMention,
    Mention,
    SpanAnnotation,
    TextVersion,
    ensure_entity_profile,
)
from app.services.corpus import create_processing_run, create_span_annotation

router = APIRouter()


def _sentence_for_span(text: str, start_char: int, end_char: int) -> str:
    left = text.rfind(".", 0, start_char)
    left = max(left, text.rfind("\n", 0, start_char))
    right_candidates = [i for i in [text.find(".", end_char), text.find("\n", end_char)] if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left + 1:right + 1].strip()


def _validate_span(article: Article, start_char: int, end_char: int) -> str:
    text = article.content_text or ""
    if start_char < 0 or end_char <= start_char or end_char > len(text):
        raise HTTPException(400, "Invalid text selection range")
    surface = text[start_char:end_char].strip()
    if not surface:
        raise HTTPException(400, "Selection cannot be empty")
    return surface


def _entity_alt_labels(entity: Entity) -> list[str]:
    return [alias.alias for alias in entity.aliases if alias.alias]


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


def _serialize_article(article: Article, db: Session) -> dict:
    current_text = article.content_text or ""
    return {
        "id": article.id,
        "article_id": article.id,
        "current_text_version_id": article.current_text_version_id,
        "profile_id": article.profile_id,
        "filename": article.filename,
        "filetype": article.filetype,
        "language": article.language,
        "publication_date": article.publication_date.isoformat() if article.publication_date else None,
        "uploaded_at": article.uploaded_at.isoformat() if article.uploaded_at else None,
        "text_length": len(current_text),
        "mention_count": db.query(Mention).filter(Mention.document_id == article.id).count(),
    }


def _article_query(db: Session, profile_id: str):
    return db.query(Article)


@router.get("/articles")
def list_articles(
    profile_id: str = Query("", description="Deprecated; ignored"),
    db: Session = Depends(get_db),
):
    """List corpus articles as read-only context for entity curation."""
    articles = _article_query(db, profile_id).order_by(Article.uploaded_at.desc()).all()
    return [_serialize_article(article, db) for article in articles]


@router.get("/articles/{article_id}/entity-context")
def get_article_entity_context(article_id: str, db: Session = Depends(get_db)):
    """Return article text plus EntityManager mentions/coreference context."""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")

    mentions = db.query(Mention).filter(Mention.document_id == article_id).all()
    entity_ids = {mention.entity_id for mention in mentions}
    entities = {
        entity.id: entity
        for entity in db.query(Entity).filter(Entity.id.in_(entity_ids)).all()
    } if entity_ids else {}

    coref_chains = (
        db.query(CoreferenceChain)
        .filter(CoreferenceChain.document_id == article_id)
        .order_by(CoreferenceChain.chain_index)
        .all()
    )

    return {
        **_serialize_article(article, db),
        "content_text": article.content_text,
        "mentions": [
            {
                "id": mention.id,
                "annotation_id": mention.annotation_id,
                "entity_id": mention.entity_id,
                "surface_form": mention.surface_form,
                "start_char": mention.start_char,
                "end_char": mention.end_char,
                "sentence": _mention_sentence(mention),
                "review_status": mention.review_status,
                "entity": {
                    "id": entities[mention.entity_id].id,
                    "canonical_name": entities[mention.entity_id].canonical_name,
                    "entity_type": entities[mention.entity_id].entity_type,
                    "alternative_labels": _entity_alt_labels(entities[mention.entity_id]),
                    "ontology_individual_uri": entities[mention.entity_id].ontology_individual_uri,
                    "wikidata_uri": entities[mention.entity_id].wikidata_uri,
                    "dbpedia_uri": entities[mention.entity_id].dbpedia_uri,
                    "worldcat_uri": entities[mention.entity_id].worldcat_uri,
                    "image_url": entities[mention.entity_id].image_url,
                    "review_status": entities[mention.entity_id].review_status,
                } if mention.entity_id in entities else None,
            }
            for mention in mentions
        ],
        "coreference_chains": [
            {
                "chain_id": chain.id,
                "chain_index": chain.chain_index,
                "entity_id": chain.entity_id,
                "members": [
                    {
                        "surface_form": member.surface_form,
                        "start_char": member.start_char,
                        "end_char": member.end_char,
                    }
                    for member in db.query(CoreferenceMember)
                    .filter(CoreferenceMember.chain_id == chain.id)
                    .order_by(CoreferenceMember.start_char)
                    .all()
                ],
            }
            for chain in coref_chains
        ],
    }


@router.get("/text-versions/{text_version_id}/entity-mentions")
def list_text_version_entity_mentions(text_version_id: str, db: Session = Depends(get_db)):
    """List EntityManager mentions for a shared corpus text version."""
    text_version = db.query(TextVersion).filter(TextVersion.id == text_version_id).first()
    if not text_version:
        raise HTTPException(404, "Text version not found")

    mentions = (
        db.query(EntityMention)
        .join(EntityMention.annotation)
        .filter(SpanAnnotation.text_version_id == text_version_id)
        .all()
    )
    return [
        {
            "id": mention.id,
            "annotation_id": mention.annotation_id,
            "entity_id": mention.entity_id,
            "surface_form": mention.surface_form,
            "start_char": mention.start_char,
            "end_char": mention.end_char,
            "review_status": mention.review_status,
        }
        for mention in mentions
    ]


class ManualEntityRequest(BaseModel):
    label: str | None = None
    start_char: int
    end_char: int
    entity_type: str = "MISC"


@router.post("/articles/{article_id}/entities")
def create_manual_entity_annotation(
    article_id: str,
    body: ManualEntityRequest,
    db: Session = Depends(get_db),
):
    """Create a manual entity annotation from selected article text."""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    if not article.current_text_version:
        raise HTTPException(400, "Article has no current text version")

    surface = _validate_span(article, body.start_char, body.end_char)
    entity = Entity(
        canonical_name=(body.label or surface).strip() or surface,
        entity_type=(body.entity_type or "MISC").strip().upper() or "MISC",
        review_status="accepted",
    )
    db.add(entity)
    db.flush()

    run = create_processing_run(
        db,
        text_version_id=article.current_text_version.id,
        profile_id=None,
        tool_name="manual_entity_annotation",
        model_name=None,
        model_version=None,
        parameters={"source": "entity_renderer_selection"},
        component_slug="entity_manager",
        component_name="EIAS EntityManager",
    )
    annotation = create_span_annotation(
        db,
        processing_run_id=run.id,
        text_version_id=article.current_text_version.id,
        annotation_type="entity",
        start_char=body.start_char,
        end_char=body.end_char,
        exact_text=surface,
        motivation="identifying",
        body={
            "label": entity.entity_type,
            "review_status": "accepted",
            "sentence": _sentence_for_span(article.content_text or "", body.start_char, body.end_char),
        },
    )
    mention = EntityMention(
        annotation_id=annotation.id,
        entity_id=entity.id,
        surface_form=surface,
        linking_method="manual",
        review_status="accepted",
    )
    db.add(mention)
    ensure_entity_profile(db, entity, None)
    db.commit()
    return {
        "status": "created",
        "entity_id": entity.id,
        "mention_id": mention.id,
        "annotation_id": annotation.id,
    }


@router.delete("/articles/{article_id}/mentions/{mention_id}")
def delete_manual_entity_annotation(article_id: str, mention_id: str, db: Session = Depends(get_db)):
    """Delete one entity mention/span annotation without deleting its canonical entity."""
    mention = db.query(EntityMention).filter(EntityMention.id == mention_id).first()
    if not mention or mention.document_id != article_id:
        raise HTTPException(404, "Mention not found")
    annotation = mention.annotation
    annotation_id = mention.annotation_id
    db.delete(mention)
    db.flush()
    remaining = db.query(EntityMention).filter(EntityMention.annotation_id == annotation_id).count()
    if annotation and remaining == 0:
        db.delete(annotation)
    db.commit()
    return {"status": "deleted", "mention_id": mention_id}
