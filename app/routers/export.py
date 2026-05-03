"""Export endpoints — download entity database in various formats."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.export import export_json, export_csv, export_rdf_xml

router = APIRouter()


@router.get("/{fmt}")
def download_export(fmt: str, db: Session = Depends(get_db)):
    """Download the entity database in the specified format.

    Supported formats: json, csv, rdf
    """
    if fmt == "json":
        content = export_json(db)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=entities.json"},
        )

    elif fmt == "csv":
        content = export_csv(db)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=entities.csv"},
        )

    elif fmt == "rdf":
        content = export_rdf_xml(db)
        return Response(
            content=content,
            media_type="application/rdf+xml",
            headers={"Content-Disposition": "attachment; filename=entities.rdf"},
        )

    else:
        raise HTTPException(400, f"Unsupported format: {fmt}. Use: json, csv, rdf")
