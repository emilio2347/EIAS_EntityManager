"""Named Entity Recognition pipeline using spaCy."""

from __future__ import annotations

import json
import logging
from typing import Any

import spacy
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.config import SPACY_MODEL
from app.models import Entity, Mention, OntologyMapping
from app.services.app_settings import get_pipeline_settings

logger = logging.getLogger(__name__)

# Lazy-loaded spaCy pipeline
_nlp = None
_nlp_key: tuple[str, bool] | None = None


def get_nlp(model_name: str | None = None, coreference_enabled: bool = True):
    """Load the spaCy model once and return it."""
    global _nlp, _nlp_key
    resolved_model = model_name or SPACY_MODEL
    cache_key = (resolved_model, coreference_enabled)
    if _nlp is None or _nlp_key != cache_key:
        logger.info("Loading spaCy model: %s", resolved_model)
        _nlp = spacy.load(resolved_model)
        _nlp_key = cache_key
        # Try to add coreferee if available
        if coreference_enabled:
            try:
                import coreferee  # noqa: F401
                if "coreferee" not in _nlp.pipe_names:
                    _nlp.add_pipe("coreferee")
                    logger.info("coreferee pipeline component added")
            except (ImportError, Exception) as e:
                logger.warning("coreferee not available: %s", e)
    return _nlp


def extract_entities(
    text: str,
    document_id: str,
    db: Session,
    allowed_types: set[str] | None = None,
    profile_id: str | None = None,
) -> list[dict[str, Any]]:
    """Run NER on text, deduplicate against existing entities, and persist.

    Returns a list of dicts describing newly created/matched entities.
    If `allowed_types` is provided, only entities with labels in that set are kept.
    """
    settings = get_pipeline_settings(db)
    nlp = get_nlp(settings.spacy_model, settings.coreference_enabled)
    doc = nlp(text)

    # Load ontology mappings
    mappings: dict[str, str] = {}
    mapping_labels: dict[str, str] = {}
    for m in db.query(OntologyMapping).all():
        mappings[m.spacy_label] = m.ontology_class_uri
        mapping_labels[m.spacy_label] = m.ontology_class_label or ""

    results: list[dict[str, Any]] = []

    for ent in doc.ents:
        if allowed_types is not None and ent.label_ not in allowed_types:
            continue

        # Find the enclosing sentence
        sentence_text = ent.sent.text if ent.sent else ""

        # Try to match to an existing entity
        entity = _find_or_create_entity(
            db=db,
            name=ent.text,
            label=ent.label_,
            ontology_uri=mappings.get(ent.label_),
            profile_id=profile_id,
            fuzzy_match_threshold=settings.fuzzy_match_threshold,
        )

        # Create mention
        mention = Mention(
            entity_id=entity.id,
            document_id=document_id,
            surface_form=ent.text,
            start_char=ent.start_char,
            end_char=ent.end_char,
            sentence=sentence_text,
        )
        db.add(mention)

        results.append({
            "entity_id": entity.id,
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "surface_form": ent.text,
            "start_char": ent.start_char,
            "end_char": ent.end_char,
            "is_new": entity in db.new,
        })

    db.commit()
    return results


def _alt_labels_of(entity: Entity) -> list[str]:
    raw = entity.alternative_labels or "[]"
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data if x]
    except (ValueError, TypeError):
        pass
    return []


def _find_or_create_entity(
    db: Session,
    name: str,
    label: str,
    ontology_uri: str | None,
    profile_id: str | None,
    fuzzy_match_threshold: int,
) -> Entity:
    """Find an existing entity by exact-or-fuzzy name match, or create a new one.

    Matches against canonical_name AND any alternative_labels — so once two
    surface forms have been merged, future occurrences of either form route
    to the merged entity.
    """
    name_lower = name.lower()

    # Exact match against canonical_name
    existing = (
        db.query(Entity)
        .filter(
            Entity.canonical_name == name,
            Entity.entity_type == label,
            Entity.profile_id == profile_id,
        )
        .first()
    )
    if existing:
        return existing

    candidates = (
        db.query(Entity)
        .filter(Entity.entity_type == label, Entity.profile_id == profile_id)
        .all()
    )

    # Exact match against any alt label
    for candidate in candidates:
        if name in _alt_labels_of(candidate):
            return candidate

    # Fuzzy match against canonical_name and alt labels
    for candidate in candidates:
        names_to_check = [candidate.canonical_name, *_alt_labels_of(candidate)]
        for cname in names_to_check:
            if fuzz.ratio(name_lower, cname.lower()) >= fuzzy_match_threshold:
                return candidate

    # Create new
    entity = Entity(
        profile_id=profile_id,
        canonical_name=name,
        entity_type=label,
        ontology_class_uri=ontology_uri,
        alternative_labels="[]",
    )
    db.add(entity)
    db.flush()  # get ID
    return entity
