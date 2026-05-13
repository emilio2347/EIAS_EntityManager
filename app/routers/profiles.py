"""Extraction Profile endpoints — manage NER type filters used during ingest."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AppSetting, Document, Entity, ExtractionProfile

router = APIRouter()


# Default labels spaCy's en_core_web_* models can produce, plus locally useful
# labels that can be assigned manually or emitted by a custom trained pipeline.
BUILTIN_NER_TYPES: list[str] = [
    "PERSON", "ORG", "GPE", "LOC", "WORK_OF_ART", "EVENT",
    "DATE", "NORP", "FAC", "PRODUCT", "LAW", "LANGUAGE",
    "MONEY", "QUANTITY", "ORDINAL", "CARDINAL", "PERCENT", "TIME", "MISC",
    "CONCEPT",
]
CUSTOM_NER_TYPES_KEY = "ner.custom_types"
NER_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")


def _normalize_type_label(label: str) -> str:
    normalized = (label or "").strip().upper().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized)
    if not NER_TYPE_RE.match(normalized):
        raise HTTPException(
            400,
            "NER label must be 2-32 characters using uppercase letters, numbers, and underscores, and must start with a letter",
        )
    return normalized


def _ordered_unique(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        normalized = _normalize_type_label(label)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _load_custom_types(db: Session) -> list[str]:
    setting = db.query(AppSetting).filter(AppSetting.key == CUSTOM_NER_TYPES_KEY).first()
    if not setting:
        return []
    try:
        data = json.loads(setting.value)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    labels = []
    for value in data:
        try:
            labels.append(_normalize_type_label(str(value)))
        except HTTPException:
            continue
    return _ordered_unique(labels)


def _store_custom_types(db: Session, labels: list[str]) -> list[str]:
    custom = _ordered_unique(labels)
    setting = db.query(AppSetting).filter(AppSetting.key == CUSTOM_NER_TYPES_KEY).first()
    value = json.dumps(custom)
    if setting:
        setting.value = value
    else:
        db.add(AppSetting(key=CUSTOM_NER_TYPES_KEY, value=value))
    db.commit()
    return custom


def _known_entity_types(db: Session) -> list[str]:
    labels = [row[0] for row in db.query(Entity.entity_type).distinct().all() if row[0]]
    return _ordered_unique(labels)


def list_ner_types(db: Session) -> list[str]:
    return _ordered_unique([*BUILTIN_NER_TYPES, *_load_custom_types(db), *_known_entity_types(db)])


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
                allowed_types=json.dumps(list_ner_types(db)),
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
def list_known_types(db: Session = Depends(get_db)):
    """List all NER labels the UI can offer when defining a profile."""
    return {"types": list_ner_types(db), "custom_types": _load_custom_types(db)}


class NerTypeCreate(BaseModel):
    label: str


@router.post("/types")
def create_custom_type(body: NerTypeCreate, db: Session = Depends(get_db)):
    """Create a custom NER label for manual tagging and trained pipelines."""
    label = _normalize_type_label(body.label)
    custom = _load_custom_types(db)
    if label not in BUILTIN_NER_TYPES and label not in custom:
        custom.append(label)
        custom = _store_custom_types(db, custom)
    return {
        "status": "created",
        "label": label,
        "types": list_ner_types(db),
        "custom_types": custom,
    }


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

    cleaned_types = _ordered_unique([t for t in body.allowed_types if t and t.strip()])
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
        cleaned = _ordered_unique([t for t in body.allowed_types if t and t.strip()])
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
