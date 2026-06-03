"""TopicManager keyword extraction and FAST subject assignment helpers."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.models import (
    Article,
    FastSubject,
    KeywordFastAssignment,
    KeywordFastCandidate,
    NLPComponent,
    ProcessingRun,
    SpanAnnotation,
    TopicKeyword,
)
from app.services.corpus import create_processing_run, create_span_annotation
from app.services.app_settings import (
    TopicManagerSettings,
    get_pipeline_settings,
    get_topic_manager_settings,
)
from app.services.ner import get_nlp

FAST_SUGGEST_URL = "https://fast.oclc.org/searchfast/fastsuggest"

FAST_FACETS = {
    "all": "suggestall",
    "personal": "suggest00",
    "corporate": "suggest10",
    "event": "suggest11",
    "title": "suggest30",
    "topical": "suggest50",
    "geographic": "suggest51",
    "form": "suggest55",
}

TAG_FACETS = {
    "100": "Personal",
    "110": "Corporate",
    "111": "Event",
    "130": "Uniform title",
    "150": "Topical",
    "151": "Geographic",
    "155": "Form/Genre",
}

DOMAIN_STOPWORDS = {
    "about", "above", "after", "again", "against", "also", "among", "because",
    "before", "being", "between", "both", "could", "during", "each", "from",
    "have", "into", "more", "most", "other", "over", "same", "some", "such",
    "than", "that", "their", "there", "these", "they", "this", "through",
    "under", "using", "where", "which", "while", "with", "within", "would",
    "article", "paper", "text", "study",
}

CONTENT_POS = {"NOUN", "PROPN", "ADJ", "VERB"}
NOUN_POS = {"NOUN", "PROPN"}
BOUNDARY_POS = {"ADP", "AUX", "CCONJ", "DET", "PART", "PRON", "PUNCT", "SCONJ", "SPACE", "SYM"}


@dataclass
class KeywordCandidate:
    surface_form: str
    normalized_form: str
    start_char: int
    end_char: int
    extraction_method: str


@dataclass
class KeywordExtractionResult:
    keywords: list[TopicKeyword]
    fast_autocache: dict[str, int]


def normalize_keyword(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", value.lower())).strip()


def _token_is_rejectable(token: Any) -> bool:
    normalized = normalize_keyword(getattr(token, "lemma_", "") or getattr(token, "text", ""))
    return (
        bool(getattr(token, "is_space", False))
        or bool(getattr(token, "is_punct", False))
        or bool(getattr(token, "like_num", False))
        or not normalized
        or normalized in DOMAIN_STOPWORDS
    )


def _token_is_boundary(token: Any) -> bool:
    return (
        _token_is_rejectable(token)
        or bool(getattr(token, "is_stop", False))
        or getattr(token, "pos_", "") in BOUNDARY_POS
    )


def _trim_candidate_tokens(tokens: list[Any]) -> list[Any]:
    start = 0
    end = len(tokens)
    while start < end and _token_is_boundary(tokens[start]):
        start += 1
    while end > start and _token_is_boundary(tokens[end - 1]):
        end -= 1
    return tokens[start:end]


def _normalize_tokens(tokens: list[Any]) -> str:
    parts: list[str] = []
    for token in tokens:
        lemma = getattr(token, "lemma_", "") or getattr(token, "text", "")
        if lemma == "-PRON-":
            lemma = getattr(token, "text", "")
        normalized = normalize_keyword(lemma)
        if normalized:
            parts.append(normalized)
    return normalize_keyword(" ".join(parts))


def _candidate_from_tokens(
    text: str,
    tokens: list[Any],
    method: str,
    settings: TopicManagerSettings,
) -> KeywordCandidate | None:
    trimmed = _trim_candidate_tokens(tokens)
    if not trimmed:
        return None

    content_tokens = [
        token for token in trimmed
        if not _token_is_rejectable(token)
        and not bool(getattr(token, "is_stop", False))
        and getattr(token, "pos_", "") in CONTENT_POS
    ]
    if not content_tokens:
        return None

    start = int(getattr(trimmed[0], "idx", 0))
    end = int(getattr(trimmed[-1], "idx", 0)) + len(getattr(trimmed[-1], "text", ""))
    surface = text[start:end].strip()
    normalized = _normalize_tokens(trimmed)
    word_count = len(normalized.split())

    if (
        not surface
        or not normalized
        or len(normalized) < settings.min_phrase_chars
        or word_count > settings.max_phrase_words
        or normalized in DOMAIN_STOPWORDS
    ):
        return None
    if len(content_tokens) / max(1, len(trimmed)) < 0.5:
        return None
    return KeywordCandidate(surface, normalized, start, end, method)


def _candidate_phrases(text: str, db: Session) -> list[KeywordCandidate]:
    settings = get_topic_manager_settings(db)
    pipeline_settings = get_pipeline_settings(db)
    nlp = get_nlp(pipeline_settings.spacy_model, coreference_enabled=False)
    doc = nlp(text)

    candidates: list[KeywordCandidate] = []
    try:
        noun_chunks = list(doc.noun_chunks)
    except (NotImplementedError, ValueError):
        noun_chunks = []
    for chunk in noun_chunks:
        candidate = _candidate_from_tokens(text, list(chunk), "spacy_noun_chunk_tfidf", settings)
        if candidate:
            candidates.append(candidate)

    for ent in getattr(doc, "ents", []):
        candidate = _candidate_from_tokens(text, list(ent), "spacy_entity_tfidf", settings)
        if candidate:
            candidates.append(candidate)

    if settings.unigram_mode != "none":
        allowed_pos = {"PROPN"} if settings.unigram_mode == "proper_nouns_only" else NOUN_POS
        for token in doc:
            if getattr(token, "pos_", "") not in allowed_pos or _token_is_boundary(token):
                continue
            candidate = _candidate_from_tokens(text, [token], "spacy_unigram_tfidf", settings)
            if candidate:
                candidates.append(candidate)
    return candidates


def _document_frequencies(
    db: Session,
    candidate_forms: set[str],
    article_id: str,
) -> tuple[int, dict[str, int]]:
    articles = db.query(Article).all()
    frequencies = {form: 0 for form in candidate_forms}
    seen: dict[str, set[str]] = {form: set() for form in candidate_forms}
    existing_keywords = (
        db.query(TopicKeyword.article_id, TopicKeyword.normalized_form)
        .filter(TopicKeyword.article_id != article_id)
        .filter(TopicKeyword.normalized_form.in_(candidate_forms))
        .all()
    )
    for other_article_id, normalized_form in existing_keywords:
        if normalized_form in seen:
            seen[normalized_form].add(other_article_id)

    for other_article in articles:
        if other_article.id == article_id:
            continue
        normalized_text = normalize_keyword(other_article.content_text or "")
        if not normalized_text:
            continue
        for form in candidate_forms:
            if form and form in normalized_text:
                seen[form].add(other_article.id)
    for form, article_ids in seen.items():
        frequencies[form] = len(article_ids)
    return max(1, len(articles)), frequencies


def delete_generated_keywords_for_article(db: Session, article: Article) -> dict[str, int | str]:
    """Delete generated TopicManager keywords and spans while preserving manual terms."""
    generated_keywords = (
        db.query(TopicKeyword)
        .filter(
            TopicKeyword.article_id == article.id,
            TopicKeyword.extraction_method != "manual",
        )
        .all()
    )
    manual_keyword_ids = {
        keyword.id
        for keyword in db.query(TopicKeyword)
        .filter(
            TopicKeyword.article_id == article.id,
            TopicKeyword.extraction_method == "manual",
        )
        .all()
    }
    generated_keyword_ids = {keyword.id for keyword in generated_keywords}
    text_version_ids = [text_version.id for text_version in article.text_versions]

    deleted_annotations = 0
    if text_version_ids:
        annotations = (
            db.query(SpanAnnotation)
            .join(ProcessingRun, ProcessingRun.id == SpanAnnotation.processing_run_id)
            .join(NLPComponent, NLPComponent.id == ProcessingRun.component_id)
            .filter(
                SpanAnnotation.text_version_id.in_(text_version_ids),
                SpanAnnotation.annotation_type == "topic_keyword",
                NLPComponent.slug == "topic_manager",
            )
            .all()
        )
        for annotation in annotations:
            keyword_id = None
            try:
                body = json.loads(annotation.body_json or "{}")
                if isinstance(body, dict):
                    keyword_id = body.get("keyword_id")
            except ValueError:
                keyword_id = None
            if keyword_id not in manual_keyword_ids:
                db.delete(annotation)
                deleted_annotations += 1

    for keyword in generated_keywords:
        db.delete(keyword)
    db.commit()
    return {
        "status": "deleted",
        "article_id": article.id,
        "deleted_keywords": len(generated_keyword_ids),
        "deleted_annotations": deleted_annotations,
        "preserved_manual_keywords": len(manual_keyword_ids),
    }


def extract_keywords_for_article_with_metadata(
    db: Session,
    article: Article,
    limit: int | None = None,
) -> KeywordExtractionResult:
    """Extract deterministic per-article keywords, cache FAST candidates, and persist them."""
    if not article.current_text_version:
        raise ValueError(f"Article {article.id} has no current text version")

    settings = get_topic_manager_settings(db)
    resolved_limit = max(1, min(limit if limit is not None else settings.max_keywords, 100))
    text = article.content_text or ""
    delete_generated_keywords_for_article(db, article)

    phrases = _candidate_phrases(text, db)
    counts = Counter(candidate.normalized_form for candidate in phrases)
    total = max(1, sum(counts.values()))
    total_docs, doc_freqs = _document_frequencies(db, set(counts), article.id)
    title_text = normalize_keyword(article.filename or "")

    best: dict[str, dict[str, Any]] = {}
    for candidate in phrases:
        normalized = candidate.normalized_form
        if not normalized:
            continue
        word_count = len(normalized.split())
        tf = counts[normalized] / total
        idf = math.log((1 + total_docs) / (1 + doc_freqs.get(normalized, 0))) + 1
        method_bonus = {
            "spacy_entity_tfidf": 1.35,
            "spacy_noun_chunk_tfidf": 1.20,
            "spacy_unigram_tfidf": 0.80,
        }.get(candidate.extraction_method, 1.0)
        phrase_bonus = 1.0 + min(0.8, max(0, word_count - 1) * 0.20)
        position_bonus = 1.15 if candidate.start_char <= max(1, len(text) // 3) else 1.0
        title_bonus = 1.10 if title_text and normalized in title_text else 1.0
        score = (tf * idf * 10) * method_bonus * phrase_bonus * position_bonus * title_bonus
        current = best.get(normalized)
        if current is None or score > current["score"]:
            best[normalized] = {
                "surface_form": candidate.surface_form,
                "normalized_form": normalized,
                "start_char": candidate.start_char,
                "end_char": candidate.end_char,
                "extraction_method": candidate.extraction_method,
                "score": score,
            }

    ranked = sorted(best.values(), key=lambda item: item["score"], reverse=True)[:resolved_limit]

    run = create_processing_run(
        db,
        text_version_id=article.current_text_version.id,
        profile_id=None,
        tool_name="spacy_tfidf_keyword_extractor",
        model_name=get_pipeline_settings(db).spacy_model,
        model_version=None,
        parameters={
            "limit": resolved_limit,
            "min_phrase_chars": settings.min_phrase_chars,
            "max_phrase_words": settings.max_phrase_words,
            "unigram_mode": settings.unigram_mode,
            "candidate_count": len(phrases),
        },
        component_slug="topic_manager",
        component_name="EIAS TopicManager",
    )

    existing = {
        keyword.normalized_form: keyword
        for keyword in db.query(TopicKeyword)
        .filter(
            TopicKeyword.article_id == article.id,
            TopicKeyword.text_version_id == article.current_text_version.id,
        )
        .all()
    }

    persisted: list[TopicKeyword] = []
    for item in ranked:
        keyword = existing.get(item["normalized_form"])
        if keyword is not None and keyword.extraction_method == "manual":
            continue
        elif keyword is None:
            keyword = TopicKeyword(
                article_id=article.id,
                text_version_id=article.current_text_version.id,
                processing_run_id=run.id,
                **item,
            )
            db.add(keyword)
            db.flush()
        else:
            keyword.processing_run_id = run.id
            keyword.surface_form = item["surface_form"]
            keyword.start_char = item["start_char"]
            keyword.end_char = item["end_char"]
            keyword.extraction_method = item["extraction_method"]
            keyword.score = item["score"]
        create_span_annotation(
            db,
            processing_run_id=run.id,
            text_version_id=article.current_text_version.id,
            annotation_type="topic_keyword",
            start_char=item["start_char"],
            end_char=item["end_char"],
            exact_text=item["surface_form"],
            motivation="classifying",
            body={"keyword_id": keyword.id, "normalized_form": item["normalized_form"]},
            confidence=float(item["score"]),
        )
        persisted.append(keyword)
    db.commit()

    fast_summary = _autocache_fast_candidates(db, persisted, settings)
    run.parameters_json = json.dumps(
        {
            "limit": resolved_limit,
            "min_phrase_chars": settings.min_phrase_chars,
            "max_phrase_words": settings.max_phrase_words,
            "unigram_mode": settings.unigram_mode,
            "candidate_count": len(phrases),
            "fast_autocache": fast_summary,
        },
        ensure_ascii=False,
    )
    db.commit()
    return KeywordExtractionResult(keywords=persisted, fast_autocache=fast_summary)


def extract_keywords_for_article(db: Session, article: Article, limit: int | None = None) -> list[TopicKeyword]:
    """Extract deterministic per-article keywords and persist them."""
    return extract_keywords_for_article_with_metadata(db, article, limit=limit).keywords


def _autocache_fast_candidates(
    db: Session,
    keywords: list[TopicKeyword],
    settings: TopicManagerSettings,
) -> dict[str, int]:
    attempted = 0
    cached = 0
    failures = 0
    for keyword in keywords[:settings.fast_autocache_limit]:
        attempted += 1
        try:
            candidates = search_fast(keyword.surface_form, facet="all", rows=settings.fast_autocache_rows)
            records = persist_fast_candidates(db, keyword, candidates, keyword.surface_form)
            cached += len(records)
        except Exception:
            failures += 1
            db.rollback()
    return {"attempted": attempted, "cached": cached, "failures": failures}


def parse_fast_response(raw_text: str) -> list[dict[str, Any]]:
    """Parse OCLC FAST autosuggest JSON or JSONP into normalized candidates."""
    text = raw_text.strip()
    if not text:
        return []
    if not text.startswith(("{", "[")):
        match = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", text, flags=re.S)
        if match:
            text = match.group(1)
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        values = data.get("response") or data.get("docs") or data.get("results") or data.get("suggestions") or []
    else:
        values = data
    if isinstance(values, dict):
        values = values.get("docs") or values.get("results") or []
    if not isinstance(values, list):
        return []

    candidates: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        fast_id = str(value.get("idroot") or value.get("id") or "").strip()
        auth = str(value.get("auth") or value.get("heading") or value.get("label") or "").strip()
        if not fast_id or not auth:
            continue
        tag = str(value.get("tag") or "").strip()
        candidates.append(
            {
                "fast_id": fast_id,
                "uri": f"http://id.worldcat.org/fast/{fast_id}",
                "authorized_heading": auth,
                "facet": TAG_FACETS.get(tag[:3], value.get("facet") or ""),
                "tag": tag,
                "type": value.get("type"),
                "raw": value,
            }
        )
    return candidates


def search_fast(query: str, facet: str = "all", rows: int = 10) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []
    query_index = FAST_FACETS.get(facet or "all", facet or "suggestall")
    params = {
        "query": query,
        "queryIndex": query_index,
        "queryReturn": "suggestall,idroot,auth,tag,type,raw,breaker,indicator",
        "suggest": "autoSubject",
        "rows": max(1, min(rows, 20)),
        "callback": "testCall",
    }
    response = httpx.get(FAST_SUGGEST_URL, params=params, timeout=15)
    response.raise_for_status()
    return parse_fast_response(response.text)


def get_or_create_fast_subject(db: Session, candidate: dict[str, Any]) -> FastSubject:
    fast_id = str(candidate["fast_id"])
    subject = db.query(FastSubject).filter(FastSubject.fast_id == fast_id).first()
    if subject:
        return subject
    subject = FastSubject(
        fast_id=fast_id,
        uri=candidate.get("uri") or f"http://id.worldcat.org/fast/{fast_id}",
        authorized_heading=candidate.get("authorized_heading") or fast_id,
        facet=candidate.get("facet"),
        tag=candidate.get("tag"),
        raw_payload_json=json.dumps(candidate.get("raw") or candidate, ensure_ascii=False),
    )
    db.add(subject)
    db.flush()
    return subject


def persist_fast_candidates(
    db: Session,
    keyword: TopicKeyword,
    candidates: list[dict[str, Any]],
    query_text: str,
) -> list[KeywordFastCandidate]:
    persisted: list[KeywordFastCandidate] = []
    context = keyword.normalized_form
    for rank, candidate in enumerate(candidates, start=1):
        subject = get_or_create_fast_subject(db, candidate)
        lexical = fuzz.token_set_ratio(context, normalize_keyword(subject.authorized_heading)) / 100
        rank_score = 1 / rank
        context_score = 1.0 if context in normalize_keyword(subject.authorized_heading) else 0.0
        combined = (lexical * 0.65) + (rank_score * 0.25) + (context_score * 0.10)
        existing = (
            db.query(KeywordFastCandidate)
            .filter(
                KeywordFastCandidate.keyword_id == keyword.id,
                KeywordFastCandidate.fast_subject_id == subject.id,
                KeywordFastCandidate.query_text == query_text,
            )
            .first()
        )
        if existing:
            record = existing
            record.rank = rank
            record.lexical_score = lexical
            record.rank_score = rank_score
            record.context_score = context_score
            record.combined_score = combined
            record.raw_candidate_json = json.dumps(candidate, ensure_ascii=False)
        else:
            record = KeywordFastCandidate(
                keyword_id=keyword.id,
                fast_subject_id=subject.id,
                query_text=query_text,
                rank=rank,
                lexical_score=lexical,
                rank_score=rank_score,
                context_score=context_score,
                combined_score=combined,
                raw_candidate_json=json.dumps(candidate, ensure_ascii=False),
            )
            db.add(record)
        persisted.append(record)
    db.commit()
    return persisted


def create_assignment(
    db: Session,
    keyword: TopicKeyword,
    *,
    status: str,
    fast_subject: FastSubject | None,
    assignment_method: str,
    query_text: str | None,
    note: str | None = None,
) -> KeywordFastAssignment:
    assignment = KeywordFastAssignment(
        keyword_id=keyword.id,
        fast_subject_id=fast_subject.id if fast_subject else None,
        status=status,
        assignment_method=assignment_method,
        query_text=query_text,
        note=note,
    )
    db.add(assignment)
    keyword.review_status = "accepted" if status == "accepted" else "rejected"
    db.commit()
    db.refresh(assignment)
    return assignment
