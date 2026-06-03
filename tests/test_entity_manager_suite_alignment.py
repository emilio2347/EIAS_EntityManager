import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Entity,
    EntityMention,
    EntityReconciliationEvent,
    SpanAnnotation,
)
from app.routers import corpus, entities
from app.services.corpus import create_article_with_text, create_processing_run


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_runtime_database_check_rejects_sqlite(monkeypatch):
    import app.database as database

    monkeypatch.setattr(database, "DATABASE_URL", "sqlite:///legacy.db")
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        database.assert_runtime_database_ready()


def test_corpus_context_is_read_only_entity_evidence():
    db = _session()
    article = create_article_with_text(
        db,
        filename="shared.txt",
        filetype="txt",
        content_text="Gilles Deleuze appears here.",
        profile_id=None,
    )
    run = create_processing_run(
        db,
        text_version_id=article.current_text_version_id,
        profile_id=None,
        tool_name="spacy_ner",
        model_name="test",
        model_version="1",
    )
    entity = Entity(canonical_name="Gilles Deleuze", entity_type="PERSON", review_status="accepted")
    db.add(entity)
    db.flush()
    annotation = SpanAnnotation(
        processing_run_id=run.id,
        text_version_id=article.current_text_version_id,
        annotation_type="entity",
        start_char=0,
        end_char=14,
        exact_text="Gilles Deleuze",
        motivation="identifying",
        body_json='{"sentence":"Gilles Deleuze appears here."}',
    )
    db.add(annotation)
    db.flush()
    db.add(EntityMention(annotation_id=annotation.id, entity_id=entity.id, surface_form="Gilles Deleuze"))
    db.commit()

    listed = corpus.list_articles(profile_id="", db=db)
    assert listed[0]["id"] == article.id
    assert listed[0]["mention_count"] == 1

    detail = corpus.get_article_entity_context(article.id, db=db)
    assert detail["content_text"] == "Gilles Deleuze appears here."
    assert detail["mentions"][0]["entity"]["review_status"] == "accepted"

    with pytest.raises(HTTPException):
        corpus.get_article_entity_context("missing", db=db)


def test_entity_merge_creates_reconciliation_event():
    db = _session()
    source = Entity(canonical_name="G. Deleuze", entity_type="PERSON")
    target = Entity(canonical_name="Gilles Deleuze", entity_type="PERSON")
    db.add_all([source, target])
    db.commit()

    result = entities.merge_entities(source.id, entities.MergeRequest(target_entity_id=target.id), db=db)

    assert result["status"] == "merged"
    event = db.query(EntityReconciliationEvent).one()
    assert event.target_entity_id == target.id
    assert event.action == "merge"
    assert event.actor == "entity_manager"
