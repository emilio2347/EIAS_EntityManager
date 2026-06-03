"""Rebuild the PostgreSQL schema for the modular corpus model."""

from __future__ import annotations

from sqlalchemy import text

from app.database import Base, engine
from app import models  # noqa: F401 - register models


def reset_schema() -> None:
    with engine.begin() as conn:
        conn.execute(text("drop schema if exists public cascade"))
        conn.execute(text("create schema public"))
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    reset_schema()
    print("PostgreSQL schema rebuilt.")
