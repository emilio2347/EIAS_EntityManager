"""Named Entity Recognition pipeline using spaCy."""

from __future__ import annotations

import logging
from typing import Any

import spacy
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.config import SPACY_MODEL, SPACY_MODEL_VERSION
from app.models import (
    Entity,
    EntityMention,
    OntologyMapping,
    entity_alias_labels,
    ensure_entity_profile,
)
from app.services.app_settings import get_pipeline_settings
from app.services.corpus import create_processing_run, create_span_annotation

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
        model_version = _nlp.meta.get("version")
        if resolved_model == SPACY_MODEL and model_version != SPACY_MODEL_VERSION:
            raise RuntimeError(
                f"{SPACY_MODEL} {SPACY_MODEL_VERSION} is required, but loaded version {model_version or 'unknown'}"
            )
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
    EntityManager now runs against the single shared corpus scope.
    """
    settings = get_pipeline_settings(db)
    nlp = get_nlp(settings.spacy_model, settings.coreference_enabled)
    doc = nlp(text)
    from app.models import Article

    article = db.query(Article).filter(Article.id == document_id).first()
    if not article or not article.current_text_version:
        raise ValueError(f"Article/text version not found for {document_id}")

    run = create_processing_run(
        db,
        text_version_id=article.current_text_version.id,
        profile_id=None,
        tool_name="spacy_ner",
        model_name=settings.spacy_model,
        model_version=SPACY_MODEL_VERSION,
        parameters={
            "allowed_types": None,
            "fuzzy_match_threshold": settings.fuzzy_match_threshold,
        },
    )

    # Load ontology mappings
    mappings: dict[str, str] = {}
    mapping_labels: dict[str, str] = {}
    for m in db.query(OntologyMapping).all():
        mappings[m.spacy_label] = m.ontology_class_uri
        mapping_labels[m.spacy_label] = m.ontology_class_label or ""

    results: list[dict[str, Any]] = []

    for ent in doc.ents:
        # Find the enclosing sentence
        sentence_text = ent.sent.text if ent.sent else ""

        # Try to match to an existing entity
        entity = _find_or_create_entity(
            db=db,
            name=ent.text,
            label=ent.label_,
            ontology_uri=mappings.get(ent.label_),
            profile_id=None,
            fuzzy_match_threshold=settings.fuzzy_match_threshold,
        )

        # Create mention
        annotation = create_span_annotation(
            db,
            processing_run_id=run.id,
            text_version_id=article.current_text_version.id,
            annotation_type="entity",
            start_char=ent.start_char,
            end_char=ent.end_char,
            exact_text=ent.text,
            motivation="identifying",
            body={"label": ent.label_, "sentence": sentence_text},
        )
        mention = EntityMention(
            annotation_id=annotation.id,
            entity_id=entity.id,
            surface_form=ent.text,
            linking_method="exact_or_fuzzy",
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
    return entity_alias_labels(entity)


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
        )
        .first()
    )
    if existing:
        return existing

    candidates_query = db.query(Entity).filter(Entity.entity_type == label)
    candidates = candidates_query.all()

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
        canonical_name=name,
        entity_type=label,
        ontology_class_uri=ontology_uri,
    )
    db.add(entity)
    db.flush()  # get ID
    ensure_entity_profile(db, entity, None)
    return entity
