"""Document upload, listing, and management endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CoreferenceChain, CoreferenceMember, Document, Entity, ExtractionProfile, Mention
from app.services.ingestion import extract_text
from app.services.ner import extract_entities
from app.services.coreference import resolve_coreferences

router = APIRouter()

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".json"}


def _resolve_profile(profile_id: str | None, db: Session) -> ExtractionProfile | None:
    """Resolve an explicit profile, or fall back to the default profile."""
    if profile_id:
        profile = db.query(ExtractionProfile).filter(ExtractionProfile.id == profile_id).first()
        if profile is None:
            raise HTTPException(404, f"Extraction profile {profile_id} not found")
        return profile
    return db.query(ExtractionProfile).filter(ExtractionProfile.is_default.is_(True)).first()


def _resolve_allowed_types(profile: ExtractionProfile | None) -> set[str] | None:
    """Resolve a profile_id (or default) to a set of allowed NER labels.

    Returns None when no profile is configured (so the NER pipeline keeps every label).
    """
    if profile is None:
        return None

    try:
        types = json.loads(profile.allowed_types or "[]")
    except (ValueError, TypeError):
        types = []
    if not isinstance(types, list) or not types:
        return None
    return {str(t) for t in types}


def _load_alt_labels(entity: Entity) -> list[str]:
    try:
        data = json.loads(entity.alternative_labels or "[]")
        if isinstance(data, list):
            return [str(x) for x in data if x]
    except (ValueError, TypeError):
        pass
    return []


def _store_alt_labels(entity: Entity, labels: list[str]) -> None:
    cleaned: list[str] = []
    seen: set[str] = set()
    for label in labels:
        value = str(label).strip()
        if not value or value == entity.canonical_name or value in seen:
            continue
        cleaned.append(value)
        seen.add(value)
    entity.alternative_labels = json.dumps(cleaned, ensure_ascii=False)


def _sentence_for_span(text: str, start_char: int, end_char: int) -> str:
    left = text.rfind(".", 0, start_char)
    left = max(left, text.rfind("\n", 0, start_char))
    right_candidates = [i for i in [text.find(".", end_char), text.find("\n", end_char)] if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left + 1:right + 1].strip()


def _validate_span(doc: Document, start_char: int, end_char: int) -> str:
    if start_char < 0 or end_char <= start_char or end_char > len(doc.content_text):
        raise HTTPException(400, "Invalid text selection range")
    surface = doc.content_text[start_char:end_char].strip()
    if not surface:
        raise HTTPException(400, "Selection cannot be empty")
    return surface


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    profile_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Upload a document, extract text, run NER and coreference.

    An optional `profile_id` form field selects an extraction profile that
    constrains which NER labels are kept.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

    profile = _resolve_profile(profile_id, db)
    resolved_profile_id = profile.id if profile else None
    allowed_types = _resolve_allowed_types(profile)

    # Extract text
    content = extract_text(file.file, file.filename or "unknown.txt")

    # Store document
    doc = Document(
        profile_id=resolved_profile_id,
        filename=file.filename or "unknown",
        filetype=ext.lstrip("."),
        content_text=content,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Run NER pipeline (filtered by profile if one is active)
    ner_results = extract_entities(
        content,
        doc.id,
        db,
        allowed_types=allowed_types,
        profile_id=resolved_profile_id,
    )

    # Run coreference resolution
    coref_results = resolve_coreferences(content, doc.id, db)

    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "text_length": len(content),
        "entities_found": len(ner_results),
        "coref_chains": len(coref_results),
        "profile_used": resolved_profile_id,
    }


@router.get("")
def list_documents(
    profile_id: str = Query("", description="Restrict to documents uploaded in a profile"),
    db: Session = Depends(get_db),
):
    """List all uploaded documents."""
    query = db.query(Document)
    if profile_id:
        query = query.filter(Document.profile_id == profile_id)
    docs = query.order_by(Document.uploaded_at.desc()).all()
    return [
        {
            "id": d.id,
            "profile_id": d.profile_id,
            "filename": d.filename,
            "filetype": d.filetype,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "text_length": len(d.content_text) if d.content_text else 0,
            "mention_count": db.query(Mention).filter(Mention.document_id == d.id).count(),
        }
        for d in docs
    ]


@router.get("/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    """Get document detail with its entity mentions."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    mentions = db.query(Mention).filter(Mention.document_id == document_id).all()
    entity_ids = {m.entity_id for m in mentions}
    entities = {
        e.id: e
        for e in db.query(Entity).filter(Entity.id.in_(entity_ids)).all()
    } if entity_ids else {}

    coref_chains = db.query(CoreferenceChain).filter(
        CoreferenceChain.document_id == document_id
    ).order_by(CoreferenceChain.chain_index).all()

    return {
        "id": doc.id,
        "profile_id": doc.profile_id,
        "filename": doc.filename,
        "filetype": doc.filetype,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "content_text": doc.content_text,
        "mentions": [
            {
                "id": m.id,
                "entity_id": m.entity_id,
                "surface_form": m.surface_form,
                "start_char": m.start_char,
                "end_char": m.end_char,
                "sentence": m.sentence,
                "entity": {
                    "id": entities[m.entity_id].id,
                    "canonical_name": entities[m.entity_id].canonical_name,
                    "entity_type": entities[m.entity_id].entity_type,
                    "alternative_labels": _load_alt_labels(entities[m.entity_id]),
                    "ontology_individual_uri": entities[m.entity_id].ontology_individual_uri,
                    "wikidata_uri": entities[m.entity_id].wikidata_uri,
                    "dbpedia_uri": entities[m.entity_id].dbpedia_uri,
                    "worldcat_uri": entities[m.entity_id].worldcat_uri,
                    "image_url": entities[m.entity_id].image_url,
                } if m.entity_id in entities else None,
            }
            for m in mentions
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


class AddDocumentEntityRequest(BaseModel):
    label: str
    start_char: int
    end_char: int
    entity_type: str = "MISC"


@router.post("/{document_id}/entities")
def add_entity_from_selection(
    document_id: str,
    body: AddDocumentEntityRequest,
    db: Session = Depends(get_db),
):
    """Create an entity from selected document text and attach a mention."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    surface = _validate_span(doc, body.start_char, body.end_char)
    label = body.label.strip() or surface
    entity_type = body.entity_type.strip().upper() or "MISC"

    entity = Entity(
        profile_id=doc.profile_id,
        canonical_name=label,
        entity_type=entity_type,
        alternative_labels="[]",
    )
    db.add(entity)
    db.flush()

    mention = Mention(
        entity_id=entity.id,
        document_id=doc.id,
        surface_form=surface,
        start_char=body.start_char,
        end_char=body.end_char,
        sentence=_sentence_for_span(doc.content_text, body.start_char, body.end_char),
    )
    db.add(mention)
    db.commit()

    return {
        "status": "created",
        "entity_id": entity.id,
        "mention_id": mention.id,
    }


class AddDocumentMentionRequest(BaseModel):
    entity_id: str
    start_char: int
    end_char: int


@router.post("/{document_id}/mentions")
def append_mention_from_selection(
    document_id: str,
    body: AddDocumentMentionRequest,
    db: Session = Depends(get_db),
):
    """Append selected text as a mention of an existing entity."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    entity = db.query(Entity).filter(Entity.id == body.entity_id).first()
    if not entity:
        raise HTTPException(404, "Entity not found")
    if entity.profile_id != doc.profile_id:
        raise HTTPException(400, "Entity and document belong to different profiles")

    surface = _validate_span(doc, body.start_char, body.end_char)
    mention = Mention(
        entity_id=entity.id,
        document_id=doc.id,
        surface_form=surface,
        start_char=body.start_char,
        end_char=body.end_char,
        sentence=_sentence_for_span(doc.content_text, body.start_char, body.end_char),
    )
    db.add(mention)

    alt_labels = _load_alt_labels(entity)
    if surface != entity.canonical_name and surface not in alt_labels:
        alt_labels.append(surface)
        _store_alt_labels(entity, alt_labels)

    db.commit()
    return {
        "status": "created",
        "entity_id": entity.id,
        "mention_id": mention.id,
        "alternative_labels": _load_alt_labels(entity),
    }


@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    """Delete a document, then delete entities only mentioned in that document."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    candidate_entity_ids = {
        row[0]
        for row in db.query(Mention.entity_id)
        .filter(Mention.document_id == document_id)
        .distinct()
        .all()
    }

    db.delete(doc)
    db.flush()

    deleted_entity_ids: list[str] = []
    for entity_id in candidate_entity_ids:
        remaining_mentions = db.query(Mention).filter(Mention.entity_id == entity_id).count()
        if remaining_mentions == 0:
            entity = db.query(Entity).filter(Entity.id == entity_id).first()
            if entity:
                deleted_entity_ids.append(entity.id)
                db.delete(entity)

    db.commit()
    return {
        "status": "deleted",
        "document_id": document_id,
        "deleted_entity_count": len(deleted_entity_ids),
        "deleted_entity_ids": deleted_entity_ids,
    }
