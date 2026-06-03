"""Export endpoints — download entity database in various formats."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.export import export_json, export_csv, export_rdf_xml, export_turtle, export_json_ld

router = APIRouter()


@router.get("/{fmt}")
def download_export(
    fmt: str,
    profile_id: str = Query("", description="Deprecated; ignored"),
    entity_types: list[str] | None = Query(default=None),
    include_enrichments: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Download the entity database in the specified format.

    Supported formats: json, csv, rdf, ttl, jsonld
    """
    export_profile_id = None
    suffix = ""

    if fmt == "json":
        content = export_json(db, export_profile_id, entity_types, include_enrichments)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=entities{suffix}.json"},
        )

    elif fmt == "csv":
        content = export_csv(db, export_profile_id, entity_types, include_enrichments)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=entities{suffix}.csv"},
        )

    elif fmt == "rdf":
        content = export_rdf_xml(db, export_profile_id, entity_types, include_enrichments)
        return Response(
            content=content,
            media_type="application/rdf+xml",
            headers={"Content-Disposition": f"attachment; filename=entities{suffix}.rdf"},
        )

    elif fmt == "ttl":
        content = export_turtle(db, export_profile_id, entity_types, include_enrichments)
        return Response(
            content=content,
            media_type="text/turtle",
            headers={"Content-Disposition": f"attachment; filename=entities{suffix}.ttl"},
        )

    elif fmt == "jsonld":
        content = export_json_ld(db, export_profile_id, entity_types, include_enrichments)
        return Response(
            content=content,
            media_type="application/ld+json",
            headers={"Content-Disposition": f"attachment; filename=entities{suffix}.jsonld"},
        )

    else:
        raise HTTPException(400, f"Unsupported format: {fmt}. Use: json, csv, rdf, ttl, jsonld")
