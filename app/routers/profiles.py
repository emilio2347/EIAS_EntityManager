"""Extraction Profile endpoints — manage NER type filters used during ingest."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, Entity, ExtractionProfile

router = APIRouter()


# All NER labels spaCy's en_core_web_* models can produce.
ALL_NER_TYPES: list[str] = [
    "PERSON", "ORG", "GPE", "LOC", "WORK_OF_ART", "EVENT",
    "DATE", "NORP", "FAC", "PRODUCT", "LAW", "LANGUAGE",
    "MONEY", "QUANTITY", "ORDINAL", "CARDINAL", "PERCENT", "TIME", "MISC",
]


def _load_types(profile: ExtractionProfile) -> list[str]:
    try:
        data = json.loads(profile.allowed_types or "[]")
        if isinstance(data, list):
            return [str(t) for t in data]
    except (ValueError, TypeError):
        pass
    return []


def _serialize(profile: ExtractionProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "allowed_types": _load_types(profile),
        "is_default": bool(profile.is_default),
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
    }


def _ensure_seed_profiles(db: Session) -> None:
    """Create a default 'All Types' profile on first call if none exist."""
    profile = db.query(ExtractionProfile).filter(ExtractionProfile.is_default.is_(True)).first()
    if profile is None:
        profile = db.query(ExtractionProfile).order_by(ExtractionProfile.created_at).first()
        if profile is None:
            profile = ExtractionProfile(
                name="All Types",
                allowed_types=json.dumps(ALL_NER_TYPES),
                is_default=True,
            )
            db.add(profile)
            db.flush()
        else:
            profile.is_default = True

    # Existing databases predate profile tracks. Keep old data visible by
    # assigning unscoped documents/entities to the default track.
    db.query(Document).filter(Document.profile_id.is_(None)).update({"profile_id": profile.id})
    db.query(Entity).filter(Entity.profile_id.is_(None)).update({"profile_id": profile.id})
    db.commit()


@router.get("/types")
def list_known_types():
    """List all NER labels the UI can offer when defining a profile."""
    return {"types": ALL_NER_TYPES}


@router.get("")
def list_profiles(db: Session = Depends(get_db)):
    """List all extraction profiles."""
    _ensure_seed_profiles(db)
    profiles = db.query(ExtractionProfile).order_by(ExtractionProfile.name).all()
    return [_serialize(p) for p in profiles]


class ProfileCreate(BaseModel):
    name: str
    allowed_types: list[str]
    is_default: bool = False


@router.post("")
def create_profile(body: ProfileCreate, db: Session = Depends(get_db)):
    """Create a new extraction profile."""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if db.query(ExtractionProfile).filter(ExtractionProfile.name == name).first():
        raise HTTPException(409, f"A profile named '{name}' already exists")

    cleaned_types = [t.strip().upper() for t in body.allowed_types if t and t.strip()]
    if not cleaned_types:
        raise HTTPException(400, "At least one NER type is required")

    profile = ExtractionProfile(
        name=name,
        allowed_types=json.dumps(cleaned_types),
        is_default=body.is_default,
    )
    db.add(profile)
    db.flush()

    if body.is_default:
        # Demote any other defaults
        db.query(ExtractionProfile).filter(
            ExtractionProfile.id != profile.id
        ).update({"is_default": False})

    db.commit()
    return _serialize(profile)


class ProfileUpdate(BaseModel):
    name: str | None = None
    allowed_types: list[str] | None = None
    is_default: bool | None = None


@router.patch("/{profile_id}")
def update_profile(profile_id: str, body: ProfileUpdate, db: Session = Depends(get_db)):
    """Update an extraction profile."""
    profile = db.query(ExtractionProfile).filter(ExtractionProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Profile not found")

    if body.name is not None:
        new_name = body.name.strip()
        if not new_name:
            raise HTTPException(400, "Name cannot be empty")
        clash = (
            db.query(ExtractionProfile)
            .filter(ExtractionProfile.name == new_name, ExtractionProfile.id != profile_id)
            .first()
        )
        if clash:
            raise HTTPException(409, f"A profile named '{new_name}' already exists")
        profile.name = new_name

    if body.allowed_types is not None:
        cleaned = [t.strip().upper() for t in body.allowed_types if t and t.strip()]
        if not cleaned:
            raise HTTPException(400, "At least one NER type is required")
        profile.allowed_types = json.dumps(cleaned)

    if body.is_default is not None:
        profile.is_default = body.is_default
        if body.is_default:
            db.query(ExtractionProfile).filter(
                ExtractionProfile.id != profile.id
            ).update({"is_default": False})

    db.commit()
    return _serialize(profile)


@router.delete("/{profile_id}")
def delete_profile(profile_id: str, db: Session = Depends(get_db)):
    """Delete an extraction profile."""
    profile = db.query(ExtractionProfile).filter(ExtractionProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(404, "Profile not found")
    if db.query(ExtractionProfile).count() <= 1:
        raise HTTPException(400, "Cannot delete the last remaining profile")
    document_count = db.query(Document).filter(Document.profile_id == profile_id).count()
    entity_count = db.query(Entity).filter(Entity.profile_id == profile_id).count()
    if document_count or entity_count:
        raise HTTPException(
            400,
            f"Cannot delete a profile with {document_count} documents and {entity_count} entities",
        )
    db.delete(profile)
    db.commit()
    return {"status": "deleted"}
