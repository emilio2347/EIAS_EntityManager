"""TopicManager endpoints for keyword extraction and FAST review."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Article,
    FastSubject,
    FastSubjectSchemaMembership,
    KeywordFastAssignment,
    KeywordFastCandidate,
    TopicKeyword,
    TopicSchema,
)
from app.services.topic_modeling import (
    create_assignment,
    delete_generated_keywords_for_article,
    extract_keywords_for_article_with_metadata,
    get_or_create_fast_subject,
    normalize_keyword,
    persist_fast_candidates,
    search_fast,
)
from app.services.corpus import create_processing_run

router = APIRouter()


def _subject_payload(subject: FastSubject | None) -> dict[str, Any] | None:
    if not subject:
        return None
    return {
        "id": subject.id,
        "fast_id": subject.fast_id,
        "uri": subject.uri,
        "authorized_heading": subject.authorized_heading,
        "facet": subject.facet,
        "tag": subject.tag,
        "schemas": [
            {
                "id": membership.schema.id,
                "label": membership.schema.label,
                "schema_type": membership.schema.schema_type,
                "review_status": membership.review_status,
            }
            for membership in subject.schema_memberships
            if membership.schema
        ],
    }


def _candidate_payload(candidate: KeywordFastCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "query_text": candidate.query_text,
        "rank": candidate.rank,
        "lexical_score": candidate.lexical_score,
        "rank_score": candidate.rank_score,
        "context_score": candidate.context_score,
        "combined_score": candidate.combined_score,
        "review_status": candidate.review_status,
        "fast_subject": _subject_payload(candidate.fast_subject),
    }


def _assignment_payload(assignment: KeywordFastAssignment | None) -> dict[str, Any] | None:
    if not assignment:
        return None
    return {
        "id": assignment.id,
        "status": assignment.status,
        "assignment_method": assignment.assignment_method,
        "query_text": assignment.query_text,
        "note": assignment.note,
        "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
        "fast_subject": _subject_payload(assignment.fast_subject),
    }


def _context_snippet(article: Article, keyword: TopicKeyword, radius: int = 96) -> str:
    text = article.content_text or ""
    if keyword.start_char is None or keyword.end_char is None or not text:
        return keyword.surface_form
    start = max(0, keyword.start_char - radius)
    end = min(len(text), keyword.end_char + radius)
    snippet = text[start:end].replace("\n", " ")
    return " ".join(snippet.split())


def _keyword_payload(keyword: TopicKeyword, article: Article) -> dict[str, Any]:
    latest_assignment = (
        sorted(keyword.assignments, key=lambda item: item.created_at or item.id, reverse=True)[0]
        if keyword.assignments else None
    )
    return {
        "id": keyword.id,
        "article_id": keyword.article_id,
        "text_version_id": keyword.text_version_id,
        "surface_form": keyword.surface_form,
        "normalized_form": keyword.normalized_form,
        "start_char": keyword.start_char,
        "end_char": keyword.end_char,
        "context_snippet": _context_snippet(article, keyword),
        "extraction_method": keyword.extraction_method,
        "score": keyword.score,
        "review_status": keyword.review_status,
        "candidates": [
            _candidate_payload(candidate)
            for candidate in sorted(
                keyword.candidates,
                key=lambda item: (item.combined_score or 0, -(item.rank or 9999)),
                reverse=True,
            )
        ],
        "assignment": _assignment_payload(latest_assignment),
    }


class KeywordExtractRequest(BaseModel):
    limit: int | None = None


class ManualKeywordRequest(BaseModel):
    surface_form: str | None = None
    start_char: int
    end_char: int
    score: float | None = None


def _validate_keyword_span(article: Article, start_char: int, end_char: int) -> str:
    text = article.content_text or ""
    if start_char < 0 or end_char <= start_char or end_char > len(text):
        raise HTTPException(400, "Invalid text selection range")
    surface = text[start_char:end_char].strip()
    if not surface:
        raise HTTPException(400, "Selection cannot be empty")
    return surface


@router.post("/articles/{article_id}/keywords/extract")
def extract_article_keywords(
    article_id: str,
    body: KeywordExtractRequest | None = None,
    db: Session = Depends(get_db),
):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    limit = body.limit if body else None
    result = extract_keywords_for_article_with_metadata(
        db,
        article,
        limit=max(1, min(limit, 100)) if limit is not None else None,
    )
    return {
        "article_id": article.id,
        "keyword_count": len(result.keywords),
        "fast_autocache": result.fast_autocache,
        "keywords": [_keyword_payload(keyword, article) for keyword in result.keywords],
    }


@router.get("/articles/{article_id}/keywords")
def list_article_keywords(article_id: str, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    keywords = (
        db.query(TopicKeyword)
        .filter(TopicKeyword.article_id == article.id)
        .order_by(TopicKeyword.score.desc(), TopicKeyword.surface_form)
        .all()
    )
    return {
        "article_id": article.id,
        "filename": article.filename,
        "keywords": [_keyword_payload(keyword, article) for keyword in keywords],
    }


@router.post("/articles/{article_id}/keywords/manual")
def create_manual_keyword(article_id: str, body: ManualKeywordRequest, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    if not article.current_text_version:
        raise HTTPException(400, "Article has no current text version")
    surface = (body.surface_form or _validate_keyword_span(article, body.start_char, body.end_char)).strip()
    normalized = normalize_keyword(surface)
    if not normalized:
        raise HTTPException(400, "Keyword cannot be normalized")
    existing = (
        db.query(TopicKeyword)
        .filter(
            TopicKeyword.article_id == article.id,
            TopicKeyword.text_version_id == article.current_text_version.id,
            TopicKeyword.normalized_form == normalized,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "A keyword with this normalized form already exists for the article")

    run = create_processing_run(
        db,
        text_version_id=article.current_text_version.id,
        profile_id=None,
        tool_name="manual_keyword_annotation",
        model_name=None,
        model_version=None,
        parameters={"source": "topic_renderer_selection"},
        component_slug="topic_manager",
        component_name="EIAS TopicManager",
    )
    keyword = TopicKeyword(
        article_id=article.id,
        text_version_id=article.current_text_version.id,
        processing_run_id=run.id,
        surface_form=surface,
        normalized_form=normalized,
        start_char=body.start_char,
        end_char=body.end_char,
        extraction_method="manual",
        score=body.score if body.score is not None else 1.0,
        review_status="accepted",
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    return {"status": "created", "keyword": _keyword_payload(keyword, article)}


@router.delete("/articles/{article_id}/keywords/generated")
def delete_generated_keywords(article_id: str, db: Session = Depends(get_db)):
    """Delete generated keywords for an article while preserving manual user annotations."""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    return delete_generated_keywords_for_article(db, article)


@router.delete("/keywords/{keyword_id}")
def delete_keyword(keyword_id: str, db: Session = Depends(get_db)):
    keyword = db.query(TopicKeyword).filter(TopicKeyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(404, "Keyword not found")
    db.delete(keyword)
    db.commit()
    return {"status": "deleted", "keyword_id": keyword_id}


class FastSuggestRequest(BaseModel):
    query: str | None = None
    facet: str = "all"
    rows: int = 10


@router.post("/keywords/{keyword_id}/fast/suggest")
def suggest_fast_for_keyword(
    keyword_id: str,
    body: FastSuggestRequest | None = None,
    db: Session = Depends(get_db),
):
    keyword = db.query(TopicKeyword).filter(TopicKeyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(404, "Keyword not found")
    query_text = (body.query if body and body.query else keyword.surface_form).strip()
    facet = body.facet if body else "all"
    rows = body.rows if body else 10
    try:
        candidates = search_fast(query_text, facet=facet, rows=rows)
    except Exception as exc:
        raise HTTPException(502, f"FAST suggestion failed: {exc}") from exc
    records = persist_fast_candidates(db, keyword, candidates, query_text)
    return {
        "keyword_id": keyword.id,
        "query_text": query_text,
        "candidates": [_candidate_payload(record) for record in records],
    }


class FastAssignmentRequest(BaseModel):
    status: str = "accepted"
    candidate_id: str | None = None
    fast_subject_id: str | None = None
    fast_id: str | None = None
    uri: str | None = None
    authorized_heading: str | None = None
    facet: str | None = None
    tag: str | None = None
    query_text: str | None = None
    note: str | None = None


@router.patch("/keywords/{keyword_id}/fast-assignment")
def assign_fast_subject(keyword_id: str, body: FastAssignmentRequest, db: Session = Depends(get_db)):
    keyword = db.query(TopicKeyword).filter(TopicKeyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(404, "Keyword not found")
    status = body.status.strip().lower()
    if status not in {"accepted", "rejected"}:
        raise HTTPException(400, "status must be accepted or rejected")

    subject: FastSubject | None = None
    assignment_method = "review"
    if status == "accepted":
        if body.candidate_id:
            candidate = (
                db.query(KeywordFastCandidate)
                .filter(KeywordFastCandidate.id == body.candidate_id, KeywordFastCandidate.keyword_id == keyword.id)
                .first()
            )
            if not candidate:
                raise HTTPException(404, "Candidate not found")
            candidate.review_status = "accepted"
            subject = candidate.fast_subject
            assignment_method = "candidate_review"
        elif body.fast_subject_id:
            subject = db.query(FastSubject).filter(FastSubject.id == body.fast_subject_id).first()
            if not subject:
                raise HTTPException(404, "FAST subject not found")
            assignment_method = "manual_existing"
        elif body.fast_id and body.authorized_heading:
            subject = get_or_create_fast_subject(
                db,
                {
                    "fast_id": body.fast_id,
                    "uri": body.uri or f"http://id.worldcat.org/fast/{body.fast_id}",
                    "authorized_heading": body.authorized_heading,
                    "facet": body.facet,
                    "tag": body.tag,
                    "raw": {"source": "manual_assignment"},
                },
            )
            assignment_method = "manual"
        else:
            raise HTTPException(400, "Accepted assignments require a candidate or FAST subject")
    else:
        if body.candidate_id:
            candidate = (
                db.query(KeywordFastCandidate)
                .filter(KeywordFastCandidate.id == body.candidate_id, KeywordFastCandidate.keyword_id == keyword.id)
                .first()
            )
            if not candidate:
                raise HTTPException(404, "Candidate not found")
            candidate.review_status = "rejected"

    assignment = create_assignment(
        db,
        keyword,
        status=status,
        fast_subject=subject,
        assignment_method=assignment_method,
        query_text=body.query_text,
        note=body.note,
    )
    return {"status": "updated", "assignment": _assignment_payload(assignment)}


@router.get("/fast/search")
def fast_search(
    q: str = Query(..., min_length=1),
    facet: str = Query("all"),
    rows: int = Query(10, ge=1, le=20),
):
    try:
        return {"query": q, "facet": facet, "candidates": search_fast(q, facet=facet, rows=rows)}
    except Exception as exc:
        raise HTTPException(502, f"FAST search failed: {exc}") from exc


class SchemaCreate(BaseModel):
    label: str
    description: str | None = None
    schema_type: str = "topic"


class SchemaUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    schema_type: str | None = None
    fast_subject_id: str | None = None
    review_status: str | None = None


@router.get("/schemas")
def list_schemas(db: Session = Depends(get_db)):
    schemas = db.query(TopicSchema).order_by(TopicSchema.schema_type, TopicSchema.label).all()
    return [
        {
            "id": schema.id,
            "label": schema.label,
            "description": schema.description,
            "schema_type": schema.schema_type,
            "review_status": schema.review_status,
            "members": [
                {
                    "membership_id": membership.id,
                    "review_status": membership.review_status,
                    "fast_subject": _subject_payload(membership.fast_subject),
                }
                for membership in schema.memberships
            ],
        }
        for schema in schemas
    ]


@router.post("/schemas")
def create_schema(body: SchemaCreate, db: Session = Depends(get_db)):
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "label is required")
    if db.query(TopicSchema).filter(TopicSchema.label == label).first():
        raise HTTPException(409, "A schema with that label already exists")
    schema = TopicSchema(
        label=label,
        description=body.description.strip() if body.description else None,
        schema_type=body.schema_type.strip() or "topic",
    )
    db.add(schema)
    db.commit()
    db.refresh(schema)
    return {"id": schema.id, "label": schema.label, "description": schema.description, "schema_type": schema.schema_type}


@router.patch("/schemas/{schema_id}")
def update_schema(schema_id: str, body: SchemaUpdate, db: Session = Depends(get_db)):
    schema = db.query(TopicSchema).filter(TopicSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(404, "Schema not found")
    if body.label is not None:
        label = body.label.strip()
        if not label:
            raise HTTPException(400, "label cannot be empty")
        schema.label = label
    if body.description is not None:
        schema.description = body.description.strip() or None
    if body.schema_type is not None:
        schema.schema_type = body.schema_type.strip() or "topic"
    if body.review_status is not None:
        schema.review_status = body.review_status
    if body.fast_subject_id:
        subject = db.query(FastSubject).filter(FastSubject.id == body.fast_subject_id).first()
        if not subject:
            raise HTTPException(404, "FAST subject not found")
        existing = (
            db.query(FastSubjectSchemaMembership)
            .filter(
                FastSubjectSchemaMembership.fast_subject_id == subject.id,
                FastSubjectSchemaMembership.schema_id == schema.id,
            )
            .first()
        )
        if not existing:
            db.add(FastSubjectSchemaMembership(fast_subject_id=subject.id, schema_id=schema.id))
    db.commit()
    return {"status": "updated", "schema_id": schema.id}
