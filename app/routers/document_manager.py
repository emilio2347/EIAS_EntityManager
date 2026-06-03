"""DocumentManager endpoints for shared corpus ingestion and inspection."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from collections import defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import SOURCE_FILE_DIR
from app.database import get_db
from app.models import (
    Article,
    CoreferenceChain,
    MetadataRecord,
    NLPComponent,
    ProcessingRun,
    SourceFile,
    SpanAnnotation,
    TextVersion,
)
from app.services.corpus import create_article_with_text, create_processing_run, create_span_annotation, write_text_version_file
from app.services.ingestion import ExtractedText, extract_text_with_metadata

router = APIRouter()

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".json"}
PDF_ANNOTATION_TYPES = {
    "figure_graphic": "pdf_figure_graphic",
    "footnote": "pdf_footnote",
    "page_number": "pdf_page_number",
    "table_of_contents": "pdf_table_of_contents",
    "text_hierarchy": "pdf_text_hierarchy",
}
TEXT_HIERARCHY_LEVELS = {"title", "heading", "sub-heading", "body_text"}
DEFAULT_METADATA_TEMPLATE: dict[str, Any] = {
    "title": "",
    "subtitle": "",
    "creators": [
        {
            "name": "",
            "role": "author",
            "affiliation": "",
            "identifier": "",
        }
    ],
    "publication": {
        "date": "",
        "venue": "",
        "volume": "",
        "issue": "",
        "pages": "",
        "publisher": "",
    },
    "identifiers": {
        "doi": "",
        "isbn": "",
        "issn": "",
        "url": "",
        "canonical_uri": "",
    },
    "language": "",
    "abstract": "",
    "keywords": [],
    "source_files": {
        "formatted_pdf": "",
        "machine_readable_text": "",
    },
    "rights": {
        "copyright": "",
        "license": "",
        "access": "",
    },
    "notes": "",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_or_400(raw: str | None, field_name: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, f"{field_name} must be valid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, f"{field_name} must be a JSON object")
    return data


def _write_source_file(article_id: str, filename: str, data: bytes) -> str:
    SOURCE_FILE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "source").name.replace("/", "_")
    path = SOURCE_FILE_DIR / f"{article_id}_{safe_name}"
    path.write_bytes(data)
    return str(path)


def _source_media_type(source: SourceFile) -> str:
    mime_type = (source.mime_type or "").strip()
    if mime_type and mime_type != "application/octet-stream":
        return mime_type
    if source.original_filename and Path(source.original_filename).suffix.lower() == ".pdf":
        return "application/pdf"
    return mime_type or "application/octet-stream"


def _inline_content_disposition(filename: str) -> str:
    ascii_name = Path(filename or "source").name.replace('"', "")
    encoded = quote(ascii_name)
    return f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


def _managed_source_path(source: SourceFile) -> Path:
    if not source.storage_path:
        raise HTTPException(404, "Source file not found")
    path = Path(source.storage_path).resolve()
    try:
        path.relative_to(SOURCE_FILE_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(403, "Source file is outside managed storage") from exc
    if not path.exists():
        raise HTTPException(404, "Stored source file is missing")
    return path


def _is_pdf_source(source: SourceFile) -> bool:
    return (
        Path(source.original_filename or "").suffix.lower() == ".pdf"
        or _source_media_type(source) == "application/pdf"
    )


def _load_pdf_source(source_file_id: str, db: Session) -> tuple[SourceFile, Path]:
    source = db.query(SourceFile).filter(SourceFile.id == source_file_id).first()
    if not source:
        raise HTTPException(404, "Source file not found")
    if not _is_pdf_source(source):
        raise HTTPException(400, "Source file is not a PDF")
    return source, _managed_source_path(source)


def _open_pdf_page(source_file_id: str, page_number: int, db: Session):
    if page_number < 1:
        raise HTTPException(400, "Page number must be 1 or greater")
    source, path = _load_pdf_source(source_file_id, db)
    try:
        import fitz

        document = fitz.open(str(path))
        if page_number > document.page_count:
            page_count = document.page_count
            document.close()
            raise HTTPException(404, f"PDF has only {page_count} pages")
        return source, document, document.load_page(page_number - 1)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Could not open PDF page: {exc}") from exc


def _format_role(filename: str, requested_role: str | None = None) -> str:
    if requested_role and requested_role.strip():
        return requested_role.strip()
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "formatted_pdf"
    return "machine_readable"


def _create_text_version(
    db: Session,
    article: Article,
    *,
    extracted: ExtractedText,
    format_role: str,
) -> TextVersion:
    text_version = TextVersion(
        article_id=article.id,
        raw_text=extracted.text,
        normalized_text=extracted.text,
        sha256_raw_text=_sha256_text(extracted.text),
        sha256_normalized_text=_sha256_text(extracted.text),
        normalization_method=extracted.normalization_method,
    )
    db.add(text_version)
    db.flush()
    text_version.raw_text_path = write_text_version_file(text_version.id, extracted.text)
    text_version.normalized_text_path = text_version.raw_text_path
    if format_role == "machine_readable" or article.current_text_version_id is None:
        article.current_text_version_id = text_version.id
    return text_version


def _latest_metadata(article_id: str, db: Session) -> MetadataRecord | None:
    return (
        db.query(MetadataRecord)
        .filter(MetadataRecord.article_id == article_id)
        .order_by(MetadataRecord.created_at.desc())
        .first()
    )


def _metadata_dict(article_id: str, db: Session) -> dict[str, Any]:
    record = _latest_metadata(article_id, db)
    if not record:
        return {}
    try:
        data = json.loads(record.data_json)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _metadata_template_for_article(article: Article) -> dict[str, Any]:
    template = deepcopy(DEFAULT_METADATA_TEMPLATE)
    template["title"] = article.filename or ""
    template["language"] = article.language or ""
    template["publication"]["date"] = article.publication_date.isoformat() if article.publication_date else ""
    template["identifiers"]["canonical_uri"] = article.canonical_uri or ""
    return template


def _component_status(article: Article, db: Session) -> dict[str, dict[str, Any]]:
    text_version_ids = [tv.id for tv in article.text_versions]
    statuses: dict[str, dict[str, Any]] = {
        "entity_manager": {"status": "pending", "runs": 0, "latest_run_at": None},
        "coreference": {"status": "pending", "runs": 0, "latest_run_at": None},
        "topic_manager": {"status": "pending", "runs": 0, "latest_run_at": None},
    }
    if text_version_ids:
        runs = (
            db.query(ProcessingRun)
            .join(NLPComponent, NLPComponent.id == ProcessingRun.component_id)
            .filter(ProcessingRun.text_version_id.in_(text_version_ids))
            .order_by(ProcessingRun.started_at.desc())
            .all()
        )
        for run in runs:
            slug = run.component.slug if run.component else run.tool_name
            bucket = statuses.setdefault(slug, {"status": "pending", "runs": 0, "latest_run_at": None})
            bucket["runs"] += 1
            if bucket["latest_run_at"] is None:
                bucket["latest_run_at"] = run.started_at.isoformat() if run.started_at else None
                bucket["status"] = run.status

    coref_count = db.query(CoreferenceChain).filter(CoreferenceChain.document_id == article.id).count()
    if coref_count:
        statuses["coreference"] = {
            "status": "completed",
            "runs": coref_count,
            "latest_run_at": None,
        }
    return statuses


def _serialize_article(article: Article, db: Session, *, include_detail: bool = False) -> dict[str, Any]:
    metadata_record = _latest_metadata(article.id, db)
    metadata = _metadata_dict(article.id, db)
    source_files = db.query(SourceFile).filter(SourceFile.article_id == article.id).all()
    text_versions = (
        db.query(TextVersion)
        .filter(TextVersion.article_id == article.id)
        .order_by(TextVersion.created_at.desc())
        .all()
    )
    payload: dict[str, Any] = {
        "id": article.id,
        "article_id": article.id,
        "canonical_uri": article.canonical_uri,
        "filename": article.filename,
        "filetype": article.filetype,
        "language": article.language,
        "publication_date": article.publication_date.isoformat() if article.publication_date else None,
        "uploaded_at": article.uploaded_at.isoformat() if article.uploaded_at else None,
        "current_text_version_id": article.current_text_version_id,
        "text_length": len(article.content_text or ""),
        "metadata": metadata,
        "has_metadata": metadata_record is not None,
        "metadata_template": _metadata_template_for_article(article),
        "source_files": [
            {
                "id": source.id,
                "text_version_id": source.text_version_id,
                "source_type": source.source_type,
                "format_role": source.source_type,
                "mime_type": source.mime_type,
                "original_filename": source.original_filename,
                "storage_path": source.storage_path,
                "source_url": source.source_url,
                "sha256_file": source.sha256_file,
                "file_size_bytes": source.file_size_bytes,
            }
            for source in source_files
        ],
        "pipeline_status": _component_status(article, db),
    }
    if include_detail:
        payload.update(
            {
                "content_text": article.content_text,
                "text_versions": [
                    {
                        "id": tv.id,
                        "created_at": tv.created_at.isoformat() if tv.created_at else None,
                        "normalization_method": tv.normalization_method,
                        "is_current": tv.id == article.current_text_version_id,
                        "sha256_raw_text": tv.sha256_raw_text,
                        "sha256_normalized_text": tv.sha256_normalized_text,
                        "raw_text_path": tv.raw_text_path,
                        "normalized_text_path": tv.normalized_text_path,
                    }
                    for tv in text_versions
                ],
            }
        )
    return payload


@router.post("/articles/upload")
async def upload_article(
    file: UploadFile = File(...),
    metadata_json: str | None = Form(default=None),
    language: str | None = Form(default=None),
    publication_date: date | None = Form(default=None),
    canonical_uri: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Ingest an article into the shared corpus without running NLP pipelines."""
    filename = file.filename or "unknown.txt"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    data = await file.read()
    extracted = extract_text_with_metadata(BytesIO(data), filename)
    metadata = _json_or_400(metadata_json, "metadata_json")

    article = create_article_with_text(
        db,
        filename=filename,
        filetype=ext.lstrip("."),
        content_text=extracted.text,
        profile_id=None,
    )
    if article.current_text_version:
        article.current_text_version.normalization_method = extracted.normalization_method
    article.language = language.strip() if language and language.strip() else None
    article.publication_date = publication_date
    article.canonical_uri = canonical_uri.strip() if canonical_uri and canonical_uri.strip() else None
    db.flush()

    db.add(
        SourceFile(
            article_id=article.id,
            text_version_id=article.current_text_version_id,
            source_type=_format_role(filename),
            mime_type=file.content_type,
            original_filename=filename,
            storage_path=_write_source_file(article.id, filename, data),
            sha256_file=_sha256_bytes(data),
            file_size_bytes=len(data),
        )
    )
    if metadata:
        db.add(
            MetadataRecord(
                article_id=article.id,
                format="json",
                data_json=json.dumps(metadata, ensure_ascii=False),
            )
        )
    db.commit()
    db.refresh(article)
    return _serialize_article(article, db, include_detail=True)


@router.post("/articles/{article_id}/versions/upload")
async def upload_article_version(
    article_id: str,
    file: UploadFile = File(...),
    format_role: str | None = Form(default=None),
    set_current: bool | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Attach another source/text version to an existing article."""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    filename = file.filename or "source"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    data = await file.read()
    extracted = extract_text_with_metadata(BytesIO(data), filename)
    role = _format_role(filename, format_role)
    text_version = _create_text_version(db, article, extracted=extracted, format_role=role)
    if set_current is True:
        article.current_text_version_id = text_version.id
    elif set_current is False and article.current_text_version_id == text_version.id and article.text_versions:
        previous = (
            db.query(TextVersion)
            .filter(TextVersion.article_id == article.id, TextVersion.id != text_version.id)
            .order_by(TextVersion.created_at.desc())
            .first()
        )
        if previous:
            article.current_text_version_id = previous.id

    source = SourceFile(
        article_id=article.id,
        text_version_id=text_version.id,
        source_type=role,
        mime_type=file.content_type,
        original_filename=filename,
        storage_path=_write_source_file(article.id, filename, data),
        sha256_file=_sha256_bytes(data),
        file_size_bytes=len(data),
    )
    db.add(source)
    db.commit()
    db.refresh(article)
    return _serialize_article(article, db, include_detail=True)


@router.get("/articles")
def list_articles(db: Session = Depends(get_db)):
    articles = db.query(Article).order_by(Article.uploaded_at.desc()).all()
    return [_serialize_article(article, db) for article in articles]


@router.get("/articles/{article_id}")
def get_article(article_id: str, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    return _serialize_article(article, db, include_detail=True)


@router.get("/metadata-template")
def get_metadata_template():
    return {"template": deepcopy(DEFAULT_METADATA_TEMPLATE)}


@router.post("/metadata-template/apply-to-empty")
def apply_metadata_template_to_empty_articles(db: Session = Depends(get_db)):
    """Persist the standard metadata template only for articles with no metadata record."""
    articles = db.query(Article).order_by(Article.uploaded_at.desc()).all()
    updated_ids: list[str] = []
    for article in articles:
        if _latest_metadata(article.id, db):
            continue
        db.add(
            MetadataRecord(
                article_id=article.id,
                format="json",
                data_json=json.dumps(_metadata_template_for_article(article), ensure_ascii=False),
            )
        )
        updated_ids.append(article.id)
    db.commit()
    return {
        "status": "updated",
        "updated_count": len(updated_ids),
        "article_ids": updated_ids,
    }


class MetadataUpdate(BaseModel):
    data: dict[str, Any]
    merge: bool = True


class TextVersionUpdate(BaseModel):
    text_version_id: str


class PdfAnnotationRequest(BaseModel):
    annotation_type: str
    page_number: int = Field(ge=1)
    source_file_id: str | None = None
    label: str | None = None
    description: str | None = None
    selected_text: str | None = None
    hierarchy_level: str | None = None
    bbox: dict[str, float] | None = None


@router.put("/articles/{article_id}/metadata")
def update_metadata(article_id: str, body: MetadataUpdate, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    current = _metadata_dict(article_id, db) if body.merge else {}
    current.update(body.data)
    record = MetadataRecord(
        article_id=article.id,
        format="json",
        data_json=json.dumps(current, ensure_ascii=False),
    )
    db.add(record)
    db.commit()
    return {"status": "updated", "metadata": current, "metadata_id": record.id}


@router.patch("/articles/{article_id}/text-version")
def set_current_text_version(article_id: str, body: TextVersionUpdate, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    text_version = (
        db.query(TextVersion)
        .filter(TextVersion.id == body.text_version_id, TextVersion.article_id == article.id)
        .first()
    )
    if not text_version:
        raise HTTPException(404, "Text version not found for article")
    article.current_text_version_id = text_version.id
    db.commit()
    db.refresh(article)
    return _serialize_article(article, db, include_detail=True)


@router.get("/source-files/{source_file_id}/content")
def get_source_file_content(source_file_id: str, db: Session = Depends(get_db)):
    source = db.query(SourceFile).filter(SourceFile.id == source_file_id).first()
    if not source:
        raise HTTPException(404, "Source file not found")
    path = _managed_source_path(source)
    response = FileResponse(
        str(path),
        media_type=_source_media_type(source),
        filename=source.original_filename or path.name,
    )
    response.headers["Content-Disposition"] = _inline_content_disposition(source.original_filename or path.name)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/source-files/{source_file_id}/pdf-info")
def get_source_pdf_info(source_file_id: str, db: Session = Depends(get_db)):
    source, path = _load_pdf_source(source_file_id, db)
    try:
        import fitz

        document = fitz.open(str(path))
        try:
            pages = []
            for page_number in range(document.page_count):
                rect = document.load_page(page_number).rect
                pages.append(
                    {
                        "page_number": page_number + 1,
                        "width": rect.width,
                        "height": rect.height,
                    }
                )
            return {
                "source_file_id": source.id,
                "filename": source.original_filename,
                "page_count": document.page_count,
                "pages": pages,
            }
        finally:
            document.close()
    except Exception as exc:
        raise HTTPException(422, f"Could not read PDF metadata: {exc}") from exc


@router.get("/source-files/{source_file_id}/pages/{page_number}/image")
def get_source_pdf_page_image(
    source_file_id: str,
    page_number: int,
    scale: float = Query(1.7, ge=0.5, le=4.0),
    db: Session = Depends(get_db),
):
    try:
        import fitz

        _source, document, page = _open_pdf_page(source_file_id, page_number, db)
        try:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return Response(
                content=pixmap.tobytes("png"),
                media_type="image/png",
                headers={
                    "Cache-Control": "no-store",
                    "X-PDF-Page-Count": str(document.page_count),
                    "X-Content-Type-Options": "nosniff",
                },
            )
        finally:
            document.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Could not render PDF page: {exc}") from exc


@router.get("/source-files/{source_file_id}/pages/{page_number}/text")
def get_source_pdf_page_text(source_file_id: str, page_number: int, db: Session = Depends(get_db)):
    try:
        source, document, page = _open_pdf_page(source_file_id, page_number, db)
        try:
            rect = page.rect
            width = rect.width or 1
            height = rect.height or 1
            words = []
            for item in page.get_text("words", sort=True):
                x0, y0, x1, y1, text, block_no, line_no, word_no = item[:8]
                text = str(text).strip()
                if not text:
                    continue
                words.append(
                    {
                        "text": text,
                        "x": max(0, min(1, x0 / width)),
                        "y": max(0, min(1, y0 / height)),
                        "width": max(0, min(1, (x1 - x0) / width)),
                        "height": max(0, min(1, (y1 - y0) / height)),
                        "block": block_no,
                        "line": line_no,
                        "word": word_no,
                    }
                )
            return {
                "source_file_id": source.id,
                "page_number": page_number,
                "page_width": rect.width,
                "page_height": rect.height,
                "words": words,
            }
        finally:
            document.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Could not extract PDF text: {exc}") from exc


@router.post("/articles/{article_id}/pdf-annotations")
def create_pdf_annotation(article_id: str, body: PdfAnnotationRequest, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    stored_type = PDF_ANNOTATION_TYPES.get(body.annotation_type)
    if not stored_type:
        raise HTTPException(400, "Unsupported PDF annotation type")
    hierarchy_level = (body.hierarchy_level or "").strip().lower()
    if body.annotation_type == "text_hierarchy" and hierarchy_level not in TEXT_HIERARCHY_LEVELS:
        raise HTTPException(400, "Text hierarchy must be title, heading, sub-heading, or body_text")

    source_query = db.query(SourceFile).filter(SourceFile.article_id == article.id)
    if body.source_file_id:
        source_query = source_query.filter(SourceFile.id == body.source_file_id)
    else:
        source_query = source_query.filter(SourceFile.original_filename.ilike("%.pdf"))
    source = source_query.first()
    if not source:
        raise HTTPException(404, "PDF source file not found for article")
    if source.original_filename and Path(source.original_filename).suffix.lower() != ".pdf":
        raise HTTPException(400, "PDF annotations must reference a PDF source file")

    text_version_id = source.text_version_id or article.current_text_version_id
    if not text_version_id:
        raise HTTPException(400, "Article has no text version to anchor annotation provenance")

    run = create_processing_run(
        db,
        text_version_id=text_version_id,
        profile_id=None,
        tool_name="manual_pdf_annotation",
        model_name=None,
        model_version=None,
        parameters={"source": "entity_metadata_pdf_annotation"},
        component_slug="document_manager",
        component_name="EIAS DocumentManager",
    )
    annotation = create_span_annotation(
        db,
        processing_run_id=run.id,
        text_version_id=text_version_id,
        annotation_type=stored_type,
        start_char=0,
        end_char=0,
        exact_text=(body.selected_text or body.label or "").strip(),
        motivation="describing",
        body={
            "source_file_id": source.id,
            "page_number": body.page_number,
            "label": (body.label or "").strip(),
            "description": (body.description or "").strip(),
            "selected_text": (body.selected_text or "").strip(),
            "hierarchy_level": hierarchy_level or None,
            "bbox": body.bbox or {},
            "review_status": "accepted",
        },
    )
    db.commit()
    return {"status": "created", "annotation_id": annotation.id}


@router.get("/articles/{article_id}/pdf-annotations")
def list_pdf_annotations(article_id: str, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    text_version_ids = [tv.id for tv in article.text_versions]
    annotations = (
        db.query(SpanAnnotation)
        .filter(
            SpanAnnotation.text_version_id.in_(text_version_ids),
            SpanAnnotation.annotation_type.in_(set(PDF_ANNOTATION_TYPES.values())),
        )
        .order_by(SpanAnnotation.id)
        .all()
    )
    return {
        "article_id": article.id,
        "annotations": [
            {
                "id": annotation.id,
                "annotation_type": annotation.annotation_type,
                "body": _json_or_400(annotation.body_json, "annotation.body_json"),
                "exact_text": annotation.exact_text,
            }
            for annotation in annotations
        ],
    }


@router.get("/articles/{article_id}/annotations")
def list_annotations(
    article_id: str,
    component_slug: str = Query(""),
    annotation_type: str = Query(""),
    review_status: str = Query(""),
    start_char: int | None = Query(default=None),
    end_char: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    text_version_ids = [tv.id for tv in article.text_versions]
    query = (
        db.query(SpanAnnotation)
        .join(ProcessingRun, ProcessingRun.id == SpanAnnotation.processing_run_id)
        .join(NLPComponent, NLPComponent.id == ProcessingRun.component_id)
        .filter(SpanAnnotation.text_version_id.in_(text_version_ids))
    )
    if component_slug:
        query = query.filter(NLPComponent.slug == component_slug)
    if annotation_type:
        query = query.filter(SpanAnnotation.annotation_type == annotation_type)
    if start_char is not None:
        query = query.filter(SpanAnnotation.end_char >= start_char)
    if end_char is not None:
        query = query.filter(SpanAnnotation.start_char <= end_char)

    annotations = query.order_by(SpanAnnotation.start_char).all()
    grouped: dict[str, dict[str, Any]] = {}
    flat = []
    for annotation in annotations:
        run = annotation.processing_run
        component = run.component if run else None
        body = _json_or_400(annotation.body_json, "annotation.body_json") if annotation.body_json else {}
        status = body.get("review_status") or review_status or None
        if review_status and status != review_status:
            continue
        item = {
            "id": annotation.id,
            "processing_run_id": annotation.processing_run_id,
            "component_slug": component.slug if component else None,
            "component_name": component.name if component else None,
            "tool_name": run.tool_name if run else None,
            "annotation_type": annotation.annotation_type,
            "start_char": annotation.start_char,
            "end_char": annotation.end_char,
            "exact_text": annotation.exact_text,
            "motivation": annotation.motivation,
            "body": body,
            "confidence": annotation.confidence,
        }
        flat.append(item)
        key = item["component_slug"] or "unknown"
        grouped.setdefault(key, {"component_slug": key, "annotations": []})["annotations"].append(item)
    return {"article_id": article.id, "annotations": flat, "groups": list(grouped.values())}


@router.get("/articles/{article_id}/pipeline-status")
def get_pipeline_status(article_id: str, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    return {"article_id": article.id, "pipeline_status": _component_status(article, db)}
