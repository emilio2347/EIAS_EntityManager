"""SQLAlchemy database setup."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import DATABASE_URL


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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


# Columns to add to existing tables when missing.
# Schema changes added after the initial release go here.
_ADDITIONAL_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "documents": [
        ("profile_id", "VARCHAR"),
    ],
    "entities": [
        ("profile_id", "VARCHAR"),
        ("alternative_labels", "TEXT NOT NULL DEFAULT '[]'"),
        ("ontology_individual_uri", "VARCHAR"),
        ("image_url", "VARCHAR"),
    ],
}


def _apply_lightweight_migrations() -> None:
    """Add columns to existing tables that were introduced after initial schema."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, cols in _ADDITIONAL_COLUMNS.items():
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_def in cols:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"))


def create_tables():
    """Create all tables defined by ORM models, then apply lightweight migrations."""
    from app import models  # noqa: F401 — import so models are registered
    Base.metadata.create_all(bind=engine)
    _apply_lightweight_migrations()
