"""Explicit one-time migration from the legacy SQLite app DB to PostgreSQL."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app.config import SQLITE_LEGACY_DB_PATH
from app.database import Base, SessionLocal, engine
from app.models import (
    AppSetting,
    Entity,
    EntityAlias,
    EntityMention,
    EnrichmentProperty,
    ExtractionProfile,
    OntologyMapping,
    SpanAnnotation,
    ensure_article_profile,
    ensure_entity_profile,
)
from app.services.corpus import create_article_with_text, create_processing_run


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f"select * from {table}"))


def _count_pg(session, table_name: str) -> int:
    return int(session.execute(text(f"select count(*) from {table_name}")).scalar_one())


def _reset_pg() -> None:
    with engine.begin() as conn:
        conn.execute(text("drop schema if exists public cascade"))
        conn.execute(text("create schema public"))
    Base.metadata.create_all(bind=engine)


def _json_list(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
    except (TypeError, ValueError):
        pass
    return []


def migrate(sqlite_path: Path, *, reset: bool = False) -> dict[str, int]:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
    if reset:
        _reset_pg()
    else:
        Base.metadata.create_all(bind=engine)

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    session = SessionLocal()
    try:
        profile_map: dict[str, str] = {}
        article_map: dict[str, str] = {}
        text_version_map: dict[str, str] = {}
        entity_map: dict[str, str] = {}
        run_map: dict[str, str] = {}
        alias_counter = 0

        for idx, row in enumerate(_rows(sqlite_conn, "extraction_profiles"), start=1):
            profile = ExtractionProfile(
                id=f"prof_{idx:08d}",
                name=row["name"],
                allowed_types=row["allowed_types"],
                is_default=bool(row["is_default"]),
                created_at=_dt(row["created_at"]),
                legacy_profile_id=row["id"],
            )
            session.add(profile)
            profile_map[row["id"]] = profile.id
        session.flush()

        for setting in _rows(sqlite_conn, "app_settings"):
            session.add(AppSetting(key=setting["key"], value=setting["value"]))

        for idx, row in enumerate(_rows(sqlite_conn, "ontology_mappings"), start=1):
            session.add(
                OntologyMapping(
                    id=f"map_{idx:08d}",
                    spacy_label=row["spacy_label"],
                    ontology_class_uri=row["ontology_class_uri"],
                    ontology_class_label=row["ontology_class_label"],
                )
            )

        documents = sorted(_rows(sqlite_conn, "documents"), key=lambda r: r["uploaded_at"] or "")
        for idx, row in enumerate(documents, start=1):
            profile_id = profile_map.get(row["profile_id"])
            article = create_article_with_text(
                session,
                article_id=f"art_{idx:08d}",
                text_version_id=f"tv_{idx:08d}",
                filename=row["filename"],
                filetype=row["filetype"],
                content_text=row["content_text"],
                profile_id=profile_id,
                legacy_document_id=row["id"],
                created_at=_dt(row["uploaded_at"]),
            )
            article_map[row["id"]] = article.id
            text_version_map[row["id"]] = article.current_text_version_id
            run = create_processing_run(
                session,
                run_id=f"run_{idx:08d}",
                text_version_id=article.current_text_version_id,
                profile_id=profile_id,
                tool_name="legacy_spacy_ner_import",
                model_name=None,
                model_version=None,
                parameters={"legacy_document_id": row["id"]},
            )
            run_map[row["id"]] = run.id

        for idx, row in enumerate(_rows(sqlite_conn, "entities"), start=1):
            entity = Entity(
                id=f"ent_{idx:08d}",
                canonical_name=row["canonical_name"],
                entity_type=row["entity_type"],
                ontology_class_uri=row["ontology_class_uri"],
                ontology_individual_uri=row["ontology_individual_uri"],
                wikidata_uri=row["wikidata_uri"],
                dbpedia_uri=row["dbpedia_uri"],
                worldcat_uri=row["worldcat_uri"],
                image_url=row["image_url"],
                created_at=_dt(row["created_at"]),
                legacy_entity_id=row["id"],
            )
            session.add(entity)
            session.flush()
            entity_map[row["id"]] = entity.id
            ensure_entity_profile(session, entity, profile_map.get(row["profile_id"]))
            for alias in _json_list(row["alternative_labels"]):
                alias_counter += 1
                session.add(
                    EntityAlias(
                        id=f"alias_{alias_counter:08d}",
                        entity_id=entity.id,
                        alias=alias,
                        source="legacy_migration",
                    )
                )

        for idx, row in enumerate(_rows(sqlite_conn, "mentions"), start=1):
            text_version_id = text_version_map[row["document_id"]]
            entity_id = entity_map[row["entity_id"]]
            annotation = SpanAnnotation(
                id=f"ann_{idx:08d}",
                processing_run_id=run_map[row["document_id"]],
                text_version_id=text_version_id,
                annotation_type="entity",
                start_char=row["start_char"],
                end_char=row["end_char"],
                exact_text=row["surface_form"],
                motivation="identifying",
                body_json=json.dumps({"sentence": row["sentence"]}, ensure_ascii=False),
                legacy_mention_id=row["id"],
            )
            session.add(annotation)
            session.add(
                EntityMention(
                    id=f"men_{idx:08d}",
                    annotation_id=annotation.id,
                    entity_id=entity_id,
                    surface_form=row["surface_form"],
                    linking_method="legacy_migration",
                    legacy_mention_id=row["id"],
                )
            )

        for idx, row in enumerate(_rows(sqlite_conn, "enrichment_properties"), start=1):
            session.add(
                EnrichmentProperty(
                    id=f"prop_{idx:08d}",
                    entity_id=entity_map[row["entity_id"]],
                    property_name=row["property_name"],
                    property_uri=row["property_uri"],
                    value=row["value"],
                    source=row["source"],
                    imported_at=_dt(row["imported_at"]),
                    legacy_property_id=row["id"],
                )
            )

        session.commit()
        return {
            "articles": _count_pg(session, "articles"),
            "text_versions": _count_pg(session, "text_versions"),
            "canonical_entities": _count_pg(session, "canonical_entities"),
            "entity_mentions": _count_pg(session, "entity_mentions"),
            "span_annotations": _count_pg(session, "span_annotations"),
            "enrichment_properties": _count_pg(session, "enrichment_properties"),
            "entity_extraction_profiles": _count_pg(session, "entity_extraction_profiles"),
        }
    finally:
        session.close()
        sqlite_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, default=SQLITE_LEGACY_DB_PATH)
    parser.add_argument("--reset", action="store_true", help="Drop and recreate the PostgreSQL schema before importing.")
    args = parser.parse_args()

    counts = migrate(args.sqlite, reset=args.reset)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
