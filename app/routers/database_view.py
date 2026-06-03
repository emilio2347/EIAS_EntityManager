"""Read-only database inspection endpoints for the EIAS suite."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import Base, get_db

router = APIRouter()


def _tables() -> dict[str, Any]:
    return Base.metadata.tables


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@router.get("/tables")
def list_tables(db: Session = Depends(get_db)):
    """List all ORM-registered tables with row counts and column names."""
    payload = []
    for name, table in sorted(_tables().items()):
        count = db.execute(select(func.count()).select_from(table)).scalar_one()
        payload.append(
            {
                "name": name,
                "row_count": count,
                "columns": [column.name for column in table.columns],
            }
        )
    return payload


@router.get("/tables/{table_name}")
def read_table(
    table_name: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Read a page of rows from an ORM-registered table."""
    tables = _tables()
    table = tables.get(table_name)
    if table is None:
        raise HTTPException(404, "Table not found")

    total = db.execute(select(func.count()).select_from(table)).scalar_one()
    rows = db.execute(select(table).limit(limit).offset(offset)).mappings().all()
    table_columns = list(table.columns)
    columns = [column.name for column in table_columns]
    return {
        "name": table_name,
        "row_count": total,
        "limit": limit,
        "offset": offset,
        "columns": columns,
        "rows": [
            {column.name: _json_value(row.get(column, row.get(column.name))) for column in table_columns}
            for row in rows
        ],
    }
