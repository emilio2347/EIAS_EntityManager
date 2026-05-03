"""Document upload, listing, and management endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, ExtractionProfile, Mention
from app.services.ingestion import extract_text
from app.services.ner import extract_entities
from app.services.coreference import resolve_coreferences

router = APIRouter()

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".json"}


def _resolve_allowed_types(profile_id: str | None, db: Session) -> set[str] | None:
    """Resolve a profile_id (or default) to a set of allowed NER labels.

    Returns None when no profile is configured (so the NER pipeline keeps every label).
    """
    profile: ExtractionProfile | None = None
    if profile_id:
        profile = db.query(ExtractionProfile).filter(ExtractionProfile.id == profile_id).first()
        if profile is None:
            raise HTTPException(404, f"Extraction profile {profile_id} not found")
    else:
        profile = db.query(ExtractionProfile).filter(ExtractionProfile.is_default.is_(True)).first()
        if profile is None:
            return None

    try:
        types = json.loads(profile.allowed_types or "[]")
    except (ValueError, TypeError):
        types = []
    if not isinstance(types, list) or not types:
        return None
    return {str(t) for t in types}


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

    allowed_types = _resolve_allowed_types(profile_id, db)

    # Extract text
    content = extract_text(file.file, file.filename or "unknown.txt")

    # Store document
    doc = Document(
        filename=file.filename or "unknown",
        filetype=ext.lstrip("."),
        content_text=content,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Run NER pipeline (filtered by profile if one is active)
    ner_results = extract_entities(content, doc.id, db, allowed_types=allowed_types)

    # Run coreference resolution
    coref_results = resolve_coreferences(content, doc.id, db)

    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "text_length": len(content),
        "entities_found": len(ner_results),
        "coref_chains": len(coref_results),
        "profile_used": profile_id,
    }


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    """List all uploaded documents."""
    docs = db.query(Document).order_by(Document.uploaded_at.desc()).all()
    return [
        {
            "id": d.id,
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

    return {
        "id": doc.id,
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
            }
            for m in mentions
        ],
    }


@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    """Delete a document and its mentions."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    db.delete(doc)
    db.commit()
    return {"status": "deleted", "document_id": document_id}
