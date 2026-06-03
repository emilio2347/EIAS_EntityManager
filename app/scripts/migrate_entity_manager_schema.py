"""Apply non-destructive EntityManager-owned schema additions.

This script intentionally updates only EntityManager-owned tables/columns. It
does not create or migrate shared corpus tables owned by the wider app suite.
"""

from __future__ import annotations

from sqlalchemy import text

from app import models
from app.database import engine


ENTITY_MANAGER_TABLES = [
    models.EntityGroundingCandidate.__table__,
    models.EntityReconciliationEvent.__table__,
    models.TopicKeyword.__table__,
    models.FastSubject.__table__,
    models.KeywordFastCandidate.__table__,
    models.KeywordFastAssignment.__table__,
    models.TopicSchema.__table__,
    models.FastSubjectSchemaMembership.__table__,
]


COLUMN_MIGRATIONS = [
    (
        "canonical_entities",
        "review_status",
        "ALTER TABLE canonical_entities ADD COLUMN IF NOT EXISTS review_status VARCHAR NOT NULL DEFAULT 'machine_generated'",
    ),
    (
        "entity_mentions",
        "review_status",
        "ALTER TABLE entity_mentions ADD COLUMN IF NOT EXISTS review_status VARCHAR NOT NULL DEFAULT 'machine_generated'",
    ),
    (
        "entity_link_candidates",
        "review_status",
        "ALTER TABLE entity_link_candidates ADD COLUMN IF NOT EXISTS review_status VARCHAR NOT NULL DEFAULT 'machine_generated'",
    ),
    (
        "enrichment_properties",
        "review_status",
        "ALTER TABLE enrichment_properties ADD COLUMN IF NOT EXISTS review_status VARCHAR NOT NULL DEFAULT 'machine_generated'",
    ),
    (
        "ontology_mappings",
        "review_status",
        "ALTER TABLE ontology_mappings ADD COLUMN IF NOT EXISTS review_status VARCHAR NOT NULL DEFAULT 'machine_generated'",
    ),
    (
        "entity_extraction_profiles",
        "component_scope",
        "ALTER TABLE entity_extraction_profiles ADD COLUMN IF NOT EXISTS component_scope VARCHAR NOT NULL DEFAULT 'entity_manager'",
    ),
]


def migrate_entity_manager_schema() -> None:
    models.Base.metadata.create_all(bind=engine, tables=ENTITY_MANAGER_TABLES)
    with engine.begin() as conn:
        for _table_name, _column_name, statement in COLUMN_MIGRATIONS:
            conn.execute(text(statement))


if __name__ == "__main__":
    migrate_entity_manager_schema()
    print("EntityManager-owned schema additions applied.")
