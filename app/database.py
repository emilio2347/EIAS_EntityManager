"""SQLAlchemy database setup and runtime schema checks."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL


def _connect_args() -> dict:
    if DATABASE_URL.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(DATABASE_URL, connect_args=_connect_args())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """Create the modular corpus schema if it does not exist.

    Production schema changes should be made with the explicit schema/migration
    scripts in ``app.scripts``. This keeps local development startup forgiving
    without silently rewriting existing tables.
    """
    from app import models  # noqa: F401 - import so models are registered

    Base.metadata.create_all(bind=engine)


REQUIRED_RUNTIME_TABLES = {
    # Shared corpus tables owned by the suite.
    "articles",
    "text_versions",
    "source_files",
    "metadata_records",
    "text_segments",
    "nlp_components",
    "processing_runs",
    "span_annotations",
    # EntityManager-owned tables.
    "canonical_entities",
    "entity_aliases",
    "entity_mentions",
    "entity_link_candidates",
    "entity_grounding_candidates",
    "enrichment_properties",
    "ontology_mappings",
    "coreference_chains",
    "coreference_members",
    "entity_extraction_profiles",
    "entity_extraction_articles",
    "entity_extraction_entities",
    "entity_reconciliation_events",
    "app_settings",
    # TopicManager-owned tables.
    "topic_keywords",
    "fast_subjects",
    "keyword_fast_candidates",
    "keyword_fast_assignments",
    "topic_schemas",
    "fast_subject_schema_memberships",
}

REQUIRED_RUNTIME_COLUMNS = {
    "canonical_entities": {"entity_id", "preferred_label", "entity_type", "review_status"},
    "entity_mentions": {"mention_id", "annotation_id", "entity_id", "surface_form", "review_status"},
    "entity_link_candidates": {"candidate_id", "mention_id", "candidate_uri", "review_status"},
    "entity_grounding_candidates": {"grounding_candidate_id", "entity_id", "candidate_uri", "authority", "review_status"},
    "enrichment_properties": {"property_id", "entity_id", "property_uri", "value", "review_status"},
    "ontology_mappings": {"mapping_id", "spacy_label", "ontology_class_uri", "review_status"},
    "entity_extraction_profiles": {"profile_id", "name", "allowed_types", "component_scope"},
    "entity_reconciliation_events": {"event_id", "source_entity_id", "target_entity_id", "action"},
    "topic_keywords": {"keyword_id", "article_id", "text_version_id", "surface_form", "normalized_form", "review_status"},
    "fast_subjects": {"fast_subject_id", "fast_id", "uri", "authorized_heading"},
    "keyword_fast_candidates": {"candidate_id", "keyword_id", "fast_subject_id", "combined_score", "review_status"},
    "keyword_fast_assignments": {"assignment_id", "keyword_id", "fast_subject_id", "status"},
    "topic_schemas": {"schema_id", "label", "schema_type", "review_status"},
    "fast_subject_schema_memberships": {"membership_id", "fast_subject_id", "schema_id", "review_status"},
}


def assert_runtime_database_ready() -> None:
    """Fail fast when EntityManager is not connected to the shared PG schema."""
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError(
            "EntityManager runtime requires PostgreSQL. SQLite is supported only as a legacy migration source."
        )

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(REQUIRED_RUNTIME_TABLES - existing_tables)
    if missing_tables:
        raise RuntimeError(
            "EntityManager database schema is missing required tables: "
            + ", ".join(missing_tables)
        )

    missing_columns: list[str] = []
    for table_name, required_columns in REQUIRED_RUNTIME_COLUMNS.items():
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name in sorted(required_columns - columns):
            missing_columns.append(f"{table_name}.{column_name}")

    if missing_columns:
        raise RuntimeError(
            "EntityManager database schema is missing required columns: "
            + ", ".join(missing_columns)
        )
