import asyncio
from io import BytesIO

from fastapi import UploadFile
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Entity,
    EntityMention,
    EnrichmentProperty,
    FastSubject,
    KeywordFastAssignment,
    KeywordFastCandidate,
    MetadataRecord,
    SourceFile,
    SpanAnnotation,
    TextVersion,
    TopicKeyword,
)
from app.routers import corpus, database_view, document_manager, settings, topic_manager
from app.services import topic_modeling as topic_modeling_service
from app.services import export as export_service
from app.services.corpus import create_article_with_text
from app.services.topic_modeling import parse_fast_response


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _redirect_storage(monkeypatch, tmp_path):
    import app.routers.document_manager as document_manager_module
    import app.services.corpus as corpus_module

    monkeypatch.setattr(document_manager_module, "SOURCE_FILE_DIR", tmp_path / "source_files")
    monkeypatch.setattr(corpus_module, "TEXT_VERSION_DIR", tmp_path / "text_versions")


class _FakeToken:
    def __init__(self, text, idx, pos, lemma=None, is_stop=False):
        self.text = text
        self.idx = idx
        self.pos_ = pos
        self.lemma_ = lemma or text.lower()
        self.is_stop = is_stop
        self.is_punct = False
        self.is_space = False
        self.like_num = False


class _FakeSpan:
    def __init__(self, tokens, label=""):
        self._tokens = tokens
        self.label_ = label
        self.text = " ".join(token.text for token in tokens)
        self.start_char = tokens[0].idx
        self.end_char = tokens[-1].idx + len(tokens[-1].text)

    def __iter__(self):
        return iter(self._tokens)


class _FakeDoc:
    def __init__(self, text):
        self.text = text
        stopwords = {"this", "which", "being", "are", "and", "the"}
        raw_tokens = []
        for match in topic_modeling_service.re.finditer(r"[A-Za-z][A-Za-z0-9'-]*", text):
            value = match.group(0)
            lower = value.lower()
            if lower in stopwords:
                pos = "DET" if lower in {"this", "the"} else "AUX" if lower in {"being", "are"} else "CCONJ"
            elif value[0].isupper():
                pos = "PROPN"
            else:
                pos = "NOUN"
            lemma = {"methods": "method", "positions": "position"}.get(lower, lower)
            raw_tokens.append(_FakeToken(value, match.start(), pos, lemma=lemma, is_stop=lower in stopwords))
        self._tokens = raw_tokens
        self.noun_chunks = self._make_chunks()
        self.ents = [
            _FakeSpan(tokens, "WORK_OF_ART")
            for tokens in self.noun_chunks
            if "Cartography" in [token.text for token in tokens]
        ]

    def __iter__(self):
        return iter(self._tokens)

    def _make_chunks(self):
        chunks = []
        chunk_texts = [
            ("Digital", "mapping", "methods"),
            ("digital", "cartography"),
            ("spatial", "positions"),
            ("Critical", "Cartography"),
            ("article",),
        ]
        for chunk_values in chunk_texts:
            for idx in range(0, len(self._tokens) - len(chunk_values) + 1):
                window = self._tokens[idx:idx + len(chunk_values)]
                if tuple(token.text for token in window) == chunk_values:
                    chunks.append(_FakeSpan(window))
                    break
        return chunks


class _FakeNLP:
    def __call__(self, text):
        return _FakeDoc(text)


def _stub_topic_extraction(monkeypatch, fast_results=None, fast_error=False):
    monkeypatch.setattr(topic_modeling_service, "get_nlp", lambda *args, **kwargs: _FakeNLP())
    if fast_error:
        def _raise_fast(*args, **kwargs):
            raise RuntimeError("FAST unavailable")
        monkeypatch.setattr(topic_modeling_service, "search_fast", _raise_fast)
    else:
        monkeypatch.setattr(topic_modeling_service, "search_fast", lambda *args, **kwargs: fast_results or [])


def test_document_manager_upload_creates_corpus_source_and_metadata(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    upload = UploadFile(filename="sample.txt", file=BytesIO(b"Coordinates are not the only method."))

    result = asyncio.run(
        document_manager.upload_article(
            file=upload,
            metadata_json='{"author":"EIAS"}',
            language="en",
            publication_date=None,
            canonical_uri=None,
            db=db,
        )
    )

    assert result["filename"] == "sample.txt"
    assert result["metadata"]["author"] == "EIAS"
    assert result["pipeline_status"]["topic_manager"]["status"] == "pending"
    assert db.query(SourceFile).count() == 1

    detail = document_manager.get_article(result["id"], db=db)
    assert detail["content_text"] == "Coordinates are not the only method."
    assert detail["source_files"][0]["original_filename"] == "sample.txt"


def test_metadata_template_applies_only_to_articles_without_metadata(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    empty_article = create_article_with_text(
        db,
        filename="empty-metadata.txt",
        filetype="txt",
        content_text="No metadata yet.",
        profile_id=None,
    )
    existing_article = create_article_with_text(
        db,
        filename="existing-metadata.txt",
        filetype="txt",
        content_text="Metadata already exists.",
        profile_id=None,
    )
    db.add(
        MetadataRecord(
            article_id=existing_article.id,
            format="json",
            data_json='{"title":"Existing title"}',
        )
    )
    db.commit()

    empty_detail = document_manager.get_article(empty_article.id, db=db)
    assert empty_detail["has_metadata"] is False
    assert empty_detail["metadata_template"]["title"] == "empty-metadata.txt"

    result = document_manager.apply_metadata_template_to_empty_articles(db=db)

    assert result["updated_count"] == 1
    assert result["article_ids"] == [empty_article.id]
    assert document_manager.get_article(empty_article.id, db=db)["has_metadata"] is True
    assert document_manager.get_article(empty_article.id, db=db)["metadata"]["title"] == "empty-metadata.txt"
    assert document_manager.get_article(existing_article.id, db=db)["metadata"] == {"title": "Existing title"}


def test_article_version_upload_links_pdf_and_machine_text(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    upload = UploadFile(filename="article.txt", file=BytesIO(b"Machine readable article text."))

    article = asyncio.run(
        document_manager.upload_article(
            file=upload,
            metadata_json=None,
            language=None,
            publication_date=None,
            canonical_uri=None,
            db=db,
        )
    )

    monkeypatch.setattr(
        document_manager,
        "extract_text_with_metadata",
        lambda file, filename: document_manager.ExtractedText(
            text="OCR text from formatted PDF.",
            normalization_method="pdf_text_extraction_ocr_fallback",
            page_count=1,
            ocr_pages=[1],
        ),
    )
    pdf = UploadFile(filename="article.pdf", file=BytesIO(b"%PDF test"))
    updated = asyncio.run(
        document_manager.upload_article_version(
            article["id"],
            file=pdf,
            format_role="formatted_pdf",
            set_current=False,
            db=db,
        )
    )

    assert updated["id"] == article["id"]
    assert updated["current_text_version_id"] == article["current_text_version_id"]
    assert db.query(TextVersion).filter(TextVersion.article_id == article["id"]).count() == 2
    assert db.query(SourceFile).filter(SourceFile.article_id == article["id"]).count() == 2
    pdf_source = db.query(SourceFile).filter(SourceFile.original_filename == "article.pdf").one()
    assert pdf_source.source_type == "formatted_pdf"
    assert pdf_source.text_version.normalization_method == "pdf_text_extraction_ocr_fallback"

    switched = document_manager.set_current_text_version(
        article["id"],
        document_manager.TextVersionUpdate(text_version_id=pdf_source.text_version_id),
        db=db,
    )
    assert switched["current_text_version_id"] == pdf_source.text_version_id


def test_pdf_annotations_are_stored_as_document_manager_annotations(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    upload = UploadFile(filename="article.txt", file=BytesIO(b"Machine readable article text."))
    article = asyncio.run(
        document_manager.upload_article(
            file=upload,
            metadata_json=None,
            language=None,
            publication_date=None,
            canonical_uri=None,
            db=db,
        )
    )
    source = SourceFile(
        article_id=article["id"],
        text_version_id=article["current_text_version_id"],
        source_type="formatted_pdf",
        mime_type="application/pdf",
        original_filename="article.pdf",
        storage_path=str(tmp_path / "source_files" / "article.pdf"),
    )
    db.add(source)
    db.commit()

    created = document_manager.create_pdf_annotation(
        article["id"],
        document_manager.PdfAnnotationRequest(
            source_file_id=source.id,
            annotation_type="text_hierarchy",
            page_number=1,
            label="Introduction",
            hierarchy_level="heading",
            bbox={"x": 10, "y": 20, "width": 300, "height": 24},
        ),
        db=db,
    )

    listed = document_manager.list_pdf_annotations(article["id"], db=db)
    annotation = db.query(SpanAnnotation).filter(SpanAnnotation.id == created["annotation_id"]).one()
    assert annotation.annotation_type == "pdf_text_hierarchy"
    assert listed["annotations"][0]["body"]["hierarchy_level"] == "heading"
    assert listed["annotations"][0]["body"]["source_file_id"] == source.id


def test_pdf_source_file_content_is_rendered_inline(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    article = create_article_with_text(
        db,
        filename="pdf-render.txt",
        filetype="txt",
        content_text="Machine text.",
        profile_id=None,
    )
    db.commit()
    source_dir = tmp_path / "source_files"
    source_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = source_dir / "formatted.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test pdf\n")
    source = SourceFile(
        article_id=article.id,
        text_version_id=article.current_text_version_id,
        source_type="formatted_pdf",
        mime_type="application/octet-stream",
        original_filename="formatted.pdf",
        storage_path=str(pdf_path),
    )
    db.add(source)
    db.commit()

    response = document_manager.get_source_file_content(source.id, db=db)

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert "formatted.pdf" in response.headers["content-disposition"]


def test_pdf_source_page_image_renders_with_pymupdf(monkeypatch, tmp_path):
    import fitz

    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    article = create_article_with_text(
        db,
        filename="pdf-page.txt",
        filetype="txt",
        content_text="Machine text.",
        profile_id=None,
    )
    db.commit()
    source_dir = tmp_path / "source_files"
    source_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = source_dir / "page.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=120)
    page.insert_text((24, 64), "Rendered PDF page")
    doc.save(str(pdf_path))
    doc.close()
    source = SourceFile(
        article_id=article.id,
        text_version_id=article.current_text_version_id,
        source_type="formatted_pdf",
        mime_type=None,
        original_filename="page.pdf",
        storage_path=str(pdf_path),
    )
    db.add(source)
    db.commit()

    response = document_manager.get_source_pdf_page_image(source.id, 1, scale=1.0, db=db)
    info = document_manager.get_source_pdf_info(source.id, db=db)
    text = document_manager.get_source_pdf_page_text(source.id, 1, db=db)

    assert response.media_type == "image/png"
    assert response.headers["x-pdf-page-count"] == "1"
    assert bytes(response.body).startswith(b"\x89PNG")
    assert info["page_count"] == 1
    assert info["pages"][0]["width"] == 240
    assert "Rendered" in [word["text"] for word in text["words"]]
    assert all(0 <= word["x"] <= 1 for word in text["words"])


def test_topic_keyword_extraction_creates_processing_run_and_keywords(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    _stub_topic_extraction(monkeypatch)
    db = _session()
    upload = UploadFile(
        filename="topic.txt",
        file=BytesIO(b"Digital mapping methods shape digital cartography and spatial positions."),
    )
    article = asyncio.run(
        document_manager.upload_article(
            file=upload,
            metadata_json=None,
            language=None,
            publication_date=None,
            canonical_uri=None,
            db=db,
        )
    )

    result = topic_manager.extract_article_keywords(
        article["id"],
        topic_manager.KeywordExtractRequest(limit=10),
        db=db,
    )

    assert result["keyword_count"] > 0
    assert db.query(TopicKeyword).count() > 0
    annotations = document_manager.list_annotations(
        article["id"],
        component_slug="topic_manager",
        annotation_type="",
        review_status="",
        start_char=None,
        end_char=None,
        db=db,
    )
    assert annotations["annotations"][0]["annotation_type"] == "topic_keyword"


def test_topic_keyword_extraction_filters_stopwords_and_prefers_phrases(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    _stub_topic_extraction(monkeypatch)
    db = _session()
    article = create_article_with_text(
        db,
        filename="topic.txt",
        filetype="txt",
        content_text=(
            "This article which is being reviewed mentions Digital mapping methods, "
            "digital cartography, and spatial positions."
        ),
        profile_id=None,
    )
    db.commit()

    result = topic_manager.extract_article_keywords(
        article.id,
        topic_manager.KeywordExtractRequest(limit=10),
        db=db,
    )

    normalized = [keyword["normalized_form"] for keyword in result["keywords"]]
    assert "this" not in normalized
    assert "which" not in normalized
    assert "being" not in normalized
    assert "article" not in normalized
    assert normalized[0] == "digital mapping method"
    assert "digital cartography" in normalized
    assert result["keywords"][0]["extraction_method"] == "spacy_noun_chunk_tfidf"


def test_topic_keyword_rerun_replaces_generated_and_preserves_manual(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    _stub_topic_extraction(monkeypatch)
    db = _session()
    article = create_article_with_text(
        db,
        filename="rerun.txt",
        filetype="txt",
        content_text="Digital mapping methods shape digital cartography. AI remains.",
        profile_id=None,
    )
    db.commit()

    first = topic_manager.extract_article_keywords(article.id, topic_manager.KeywordExtractRequest(limit=10), db=db)
    manual = topic_manager.create_manual_keyword(
        article.id,
        topic_manager.ManualKeywordRequest(start_char=51, end_char=53),
        db=db,
    )
    first_generated_ids = {
        keyword["id"] for keyword in first["keywords"]
        if keyword["extraction_method"] != "manual"
    }

    second = topic_manager.extract_article_keywords(article.id, topic_manager.KeywordExtractRequest(limit=10), db=db)

    generated_ids = {
        keyword.id for keyword in db.query(TopicKeyword).filter(TopicKeyword.extraction_method != "manual").all()
    }
    manual_ids = {
        keyword.id for keyword in db.query(TopicKeyword).filter(TopicKeyword.extraction_method == "manual").all()
    }
    assert manual_ids == {manual["keyword"]["id"]}
    assert generated_ids
    assert not generated_ids.intersection(first_generated_ids)
    assert second["keyword_count"] == len(generated_ids)


def test_topic_manager_settings_persist(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()

    updated = settings.update_topic_manager_settings(
        settings.TopicManagerSettingsUpdate(
            max_keywords=12,
            min_phrase_chars=4,
            max_phrase_words=6,
            unigram_mode="all_nouns",
            fast_autocache_limit=3,
            fast_autocache_rows=2,
        ),
        db=db,
    )
    loaded = settings.get_topic_manager_settings_endpoint(db=db)

    assert updated["settings"]["max_keywords"] == 12
    assert loaded["settings"]["unigram_mode"] == "all_nouns"
    assert loaded["settings"]["fast_autocache_limit"] == 3


def test_topic_keyword_extraction_autocaches_fast_candidates_and_tolerates_failure(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    _stub_topic_extraction(
        monkeypatch,
        fast_results=[
            {
                "fast_id": "12345",
                "uri": "http://id.worldcat.org/fast/12345",
                "authorized_heading": "Digital mapping",
                "facet": "Topical",
                "tag": "150",
                "raw": {"source": "test"},
            }
        ],
    )
    db = _session()
    article = create_article_with_text(
        db,
        filename="fast-cache.txt",
        filetype="txt",
        content_text="Digital mapping methods shape digital cartography.",
        profile_id=None,
    )
    db.commit()

    result = topic_manager.extract_article_keywords(article.id, topic_manager.KeywordExtractRequest(limit=5), db=db)

    assert result["fast_autocache"]["cached"] > 0
    assert db.query(KeywordFastCandidate).count() > 0

    _stub_topic_extraction(monkeypatch, fast_error=True)
    failed_result = topic_manager.extract_article_keywords(article.id, topic_manager.KeywordExtractRequest(limit=5), db=db)

    assert failed_result["keyword_count"] > 0
    assert failed_result["fast_autocache"]["failures"] > 0


def test_fast_parsing_and_assignment_reuses_cached_subjects(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    _stub_topic_extraction(monkeypatch)
    db = _session()
    upload = UploadFile(filename="fast.txt", file=BytesIO(b"Digital mapping changes maps."))
    article = asyncio.run(
        document_manager.upload_article(
            file=upload,
            metadata_json=None,
            language=None,
            publication_date=None,
            canonical_uri=None,
            db=db,
        )
    )
    topic_manager.extract_article_keywords(article["id"], topic_manager.KeywordExtractRequest(limit=5), db=db)
    keyword = db.query(TopicKeyword).first()

    parsed = parse_fast_response(
        'testCall({"response":{"docs":[{"idroot":"12345","auth":"Digital mapping","tag":"150"}]}})'
    )
    assert parsed[0]["fast_id"] == "12345"

    records = topic_manager.persist_fast_candidates(db, keyword, parsed, "digital mapping")
    accepted = topic_manager.assign_fast_subject(
        keyword.id,
        topic_manager.FastAssignmentRequest(status="accepted", candidate_id=records[0].id),
        db=db,
    )
    topic_manager.assign_fast_subject(
        keyword.id,
        topic_manager.FastAssignmentRequest(
            status="accepted",
            fast_id="12345",
            authorized_heading="Digital mapping",
        ),
        db=db,
    )

    assert accepted["assignment"]["fast_subject"]["fast_id"] == "12345"
    assert db.query(FastSubject).count() == 1


def test_database_view_lists_tables_and_rejects_unknown(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    create_article_with_text(
        db,
        filename="db.txt",
        filetype="txt",
        content_text="Database view.",
        profile_id=None,
    )
    db.commit()

    tables = database_view.list_tables(db=db)
    assert any(table["name"] == "articles" for table in tables)

    page = database_view.read_table("articles", limit=10, offset=0, db=db)
    assert page["row_count"] == 1
    assert page["rows"][0]["primary_title"] == "db.txt"

    try:
        database_view.read_table("missing_table", db=db)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("unknown table did not raise")


def test_export_filters_entity_types_and_enrichments():
    db = _session()
    person = Entity(canonical_name="Ada Lovelace", entity_type="PERSON")
    org = Entity(canonical_name="Analytical Engine Group", entity_type="ORG")
    db.add_all([person, org])
    db.flush()
    db.add(
        EnrichmentProperty(
            entity_id=person.id,
            property_name="occupation",
            property_uri="http://example.org/occupation",
            value="mathematician",
            source="test",
        )
    )
    db.commit()

    json_payload = export_service.export_json(db, entity_types=["PERSON"], include_enrichments=False)
    assert "Ada Lovelace" in json_payload
    assert "Analytical Engine Group" not in json_payload
    assert "mathematician" not in json_payload

    csv_payload = export_service.export_csv(db, entity_types=["PERSON"], include_enrichments=True)
    assert "enrichment_json" in csv_payload
    assert "mathematician" in csv_payload

    ttl_payload = export_service.export_turtle(db, entity_types=["PERSON"], include_enrichments=False)
    assert "Ada Lovelace" in ttl_payload
    assert "mathematician" not in ttl_payload


def test_manual_entity_annotation_create_and_delete(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    article = create_article_with_text(
        db,
        filename="entity.txt",
        filetype="txt",
        content_text="Gilles Deleuze appears.",
        profile_id=None,
    )
    db.commit()

    created = corpus.create_manual_entity_annotation(
        article.id,
        corpus.ManualEntityRequest(start_char=0, end_char=14, entity_type="PERSON"),
        db=db,
    )

    assert created["entity_id"]
    assert db.query(EntityMention).count() == 1

    corpus.delete_manual_entity_annotation(article.id, created["mention_id"], db=db)
    assert db.query(EntityMention).count() == 0
    assert db.query(Entity).count() == 1


def test_manual_keyword_create_and_delete_preserves_fast_subject(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    db = _session()
    article = create_article_with_text(
        db,
        filename="keywords.txt",
        filetype="txt",
        content_text="Digital mapping changes cartography.",
        profile_id=None,
    )
    db.commit()

    created = topic_manager.create_manual_keyword(
        article.id,
        topic_manager.ManualKeywordRequest(start_char=0, end_char=15),
        db=db,
    )
    keyword = db.query(TopicKeyword).filter(TopicKeyword.id == created["keyword"]["id"]).one()
    subject = FastSubject(
        fast_id="12345",
        uri="http://id.worldcat.org/fast/12345",
        authorized_heading="Digital mapping",
    )
    db.add(subject)
    db.flush()
    candidate = KeywordFastCandidate(
        keyword_id=keyword.id,
        fast_subject_id=subject.id,
        query_text="Digital mapping",
    )
    db.add(candidate)
    db.flush()
    db.add(KeywordFastAssignment(keyword_id=keyword.id, fast_subject_id=subject.id, status="accepted"))
    db.commit()

    topic_manager.delete_keyword(keyword.id, db=db)

    assert db.query(TopicKeyword).count() == 0
    assert db.query(FastSubject).count() == 1


def test_delete_generated_keywords_preserves_manual_keywords_and_clears_spans(monkeypatch, tmp_path):
    _redirect_storage(monkeypatch, tmp_path)
    _stub_topic_extraction(monkeypatch)
    db = _session()
    article = create_article_with_text(
        db,
        filename="reprocess.txt",
        filetype="txt",
        content_text="Digital mapping methods shape cartography. AI remains.",
        profile_id=None,
    )
    db.commit()

    topic_manager.extract_article_keywords(article.id, topic_manager.KeywordExtractRequest(limit=10), db=db)
    manual = topic_manager.create_manual_keyword(
        article.id,
        topic_manager.ManualKeywordRequest(start_char=42, end_char=44),
        db=db,
    )
    before = db.query(TopicKeyword).count()
    assert before > 1

    result = topic_manager.delete_generated_keywords(article.id, db=db)

    remaining = db.query(TopicKeyword).all()
    annotations = document_manager.list_annotations(
        article.id,
        component_slug="topic_manager",
        annotation_type="topic_keyword",
        review_status="",
        start_char=None,
        end_char=None,
        db=db,
    )
    assert result["deleted_keywords"] == before - 1
    assert result["preserved_manual_keywords"] == 1
    assert [keyword.id for keyword in remaining] == [manual["keyword"]["id"]]
    assert annotations["annotations"] == []
