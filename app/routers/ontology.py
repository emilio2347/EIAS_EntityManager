"""Ontology upload, viewing, and NER-mapping endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OntologyMapping, Entity
from app.services.ontology_manager import (
    load_ontology,
    extract_classes,
    extract_individuals,
    add_individual,
    get_ontology_raw,
    get_ontology_path,
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


@router.post("/upload")
async def upload_ontology(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload or replace the .ttl ontology file."""
    if not file.filename or not file.filename.endswith(".ttl"):
        raise HTTPException(400, "Only .ttl files are accepted")

    content = await file.read()
    path = load_ontology(content, file.filename)

    classes = extract_classes()

    return {
        "status": "loaded",
        "filename": file.filename,
        "class_count": len(classes),
        "classes": classes,
    }


@router.get("/classes")
def get_classes():
    """List all classes from the loaded ontology."""
    classes = extract_classes()
    if not classes:
        return {"classes": [], "message": "No ontology loaded. Upload a .ttl file first."}
    return {"classes": classes}


@router.get("/individuals")
def get_individuals():
    """List all NamedIndividuals (Particulars) from the loaded ontology."""
    individuals = extract_individuals()
    if not individuals:
        return {"individuals": [], "message": "No ontology loaded or no individuals found."}
    return {"individuals": individuals}


class IndividualCreate(BaseModel):
    label: str
    class_uri: str | None = None


@router.post("/individuals")
def create_individual(body: IndividualCreate):
    """Add a new owl:NamedIndividual to the loaded ontology and persist it."""
    label = (body.label or "").strip()
    if not label:
        raise HTTPException(400, "Label is required")
    try:
        info = add_individual(label, body.class_uri)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"status": "created", "individual": info}


@router.get("/raw")
def get_raw_ontology():
    """Return the raw .ttl file content."""
    content = get_ontology_raw()
    if content is None:
        raise HTTPException(404, "No ontology file loaded")
    path = get_ontology_path()
    return {
        "filename": path.name if path else "unknown.ttl",
        "content": content,
    }


# --- NER ↔ Ontology Mappings ---

@router.get("/mappings")
def get_mappings(db: Session = Depends(get_db)):
    """Get all NER label → ontology class mappings."""
    mappings = db.query(OntologyMapping).order_by(OntologyMapping.spacy_label).all()
    return [
        {
            "id": m.id,
            "spacy_label": m.spacy_label,
            "ontology_class_uri": m.ontology_class_uri,
            "ontology_class_label": m.ontology_class_label,
            "review_status": m.review_status,
        }
        for m in mappings
    ]


class MappingCreate(BaseModel):
    spacy_label: str
    ontology_class_uri: str
    ontology_class_label: str = ""


class ReviewStatusRequest(BaseModel):
    review_status: str


@router.post("/mappings")
def create_mapping(body: MappingCreate, db: Session = Depends(get_db)):
    """Create or update a NER label → ontology class mapping.

    Also propagates the ontology_class_uri to all existing entities that share
    this spaCy label, so the mapping shows up in the entity preview immediately.
    """
    existing = db.query(OntologyMapping).filter(
        OntologyMapping.spacy_label == body.spacy_label
    ).first()

    if existing:
        existing.ontology_class_uri = body.ontology_class_uri
        existing.ontology_class_label = body.ontology_class_label
        status = "updated"
        mapping_id = existing.id
    else:
        mapping = OntologyMapping(
            spacy_label=body.spacy_label,
            ontology_class_uri=body.ontology_class_uri,
            ontology_class_label=body.ontology_class_label,
        )
        db.add(mapping)
        db.flush()
        status = "created"
        mapping_id = mapping.id

    # Propagate to existing entities of this type
    affected = (
        db.query(Entity)
        .filter(Entity.entity_type == body.spacy_label)
        .update({"ontology_class_uri": body.ontology_class_uri})
    )

    db.commit()
    return {"status": status, "id": mapping_id, "entities_updated": affected}


@router.patch("/mappings/{mapping_id}/review-status")
def update_mapping_review_status(
    mapping_id: str,
    body: ReviewStatusRequest,
    db: Session = Depends(get_db),
):
    """Update curation review status for one ontology mapping."""
    mapping = db.query(OntologyMapping).filter(OntologyMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(404, "Mapping not found")
    mapping.review_status = _clean_review_status(body.review_status)
    db.commit()
    return {"status": "updated", "mapping_id": mapping.id, "review_status": mapping.review_status}


@router.delete("/mappings/{mapping_id}")
def delete_mapping(mapping_id: str, db: Session = Depends(get_db)):
    """Delete a NER → ontology mapping.

    Also clears ontology_class_uri on entities that were assigned via this mapping.
    """
    mapping = db.query(OntologyMapping).filter(OntologyMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(404, "Mapping not found")

    # Clear the URI on entities that were mapped via this rule
    affected = (
        db.query(Entity)
        .filter(
            Entity.entity_type == mapping.spacy_label,
            Entity.ontology_class_uri == mapping.ontology_class_uri,
        )
        .update({"ontology_class_uri": None})
    )

    db.delete(mapping)
    db.commit()
    return {"status": "deleted", "entities_updated": affected}
