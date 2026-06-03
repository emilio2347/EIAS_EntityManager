from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Entity, EntityMention, NLPComponent, ProcessingRun, SpanAnnotation
from app.services.corpus import create_article_with_text


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_future_component_can_write_span_annotations_without_entity_tables():
    db = _session()
    article = create_article_with_text(
        db,
        filename="sample.txt",
        filetype="txt",
        content_text="A corpus can support many NLP components.",
        profile_id=None,
    )
    component = NLPComponent(slug="topic_modeling", name="Topic Modeling")
    db.add(component)
    db.flush()
    run = ProcessingRun(
        component_id=component.id,
        text_version_id=article.current_text_version_id,
        tool_name="topic-modeler",
        parameters_json="{}",
    )
    db.add(run)
    db.flush()
    annotation = SpanAnnotation(
        processing_run_id=run.id,
        text_version_id=article.current_text_version_id,
        annotation_type="topic_evidence",
        start_char=2,
        end_char=8,
        exact_text="corpus",
        motivation="classifying",
        body_json='{"topic":"infrastructure"}',
    )
    db.add(annotation)
    db.commit()

    assert db.query(SpanAnnotation).count() == 1
    assert db.query(EntityMention).count() == 0


def test_entity_mentions_link_shared_spans_to_canonical_entities():
    db = _session()
    article = create_article_with_text(
        db,
        filename="sample.txt",
        filetype="txt",
        content_text="Gilles Deleuze appears here.",
        profile_id=None,
    )
    component = NLPComponent(slug="entity_manager", name="EIAS Entity Manager")
    db.add(component)
    db.flush()
    run = ProcessingRun(
        component_id=component.id,
        text_version_id=article.current_text_version_id,
        tool_name="spacy_ner",
        parameters_json="{}",
    )
    entity = Entity(canonical_name="Gilles Deleuze", entity_type="PERSON")
    db.add_all([run, entity])
    db.flush()
    annotation = SpanAnnotation(
        processing_run_id=run.id,
        text_version_id=article.current_text_version_id,
        annotation_type="entity",
        start_char=0,
        end_char=14,
        exact_text="Gilles Deleuze",
        motivation="identifying",
        body_json="{}",
    )
    db.add(annotation)
    db.flush()
    db.add(EntityMention(annotation_id=annotation.id, entity_id=entity.id, surface_form="Gilles Deleuze"))
    db.commit()

    mention = db.query(EntityMention).one()
    assert mention.document_id == article.id
    assert mention.start_char == 0
    assert mention.entity.canonical_name == "Gilles Deleuze"

