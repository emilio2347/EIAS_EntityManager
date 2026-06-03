"""SQLAlchemy ORM models for the shared EIAS corpus database.

The public API still speaks in the current app's document/entity/mention
vocabulary, but the persisted model is organized around shared corpus objects,
component provenance, and canonical entities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    select,
)
from sqlalchemy.orm import column_property, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_prefixed_id(connection, table, column_name: str, prefix: str) -> str:
    """Return the next simple prefixed ID by scanning existing IDs.

    This app is single-user/local today. If concurrent writers become common,
    replace this with database sequences.
    """
    counters = connection.info.setdefault("eias_prefixed_id_counters", {})
    counter_key = (table.name, column_name, prefix)
    if counter_key in counters:
        counters[counter_key] += 1
        return f"{prefix}_{counters[counter_key]:08d}"

    col = table.c[column_name]
    rows = connection.execute(select(col).where(col.like(f"{prefix}_%"))).scalars()
    max_seen = 0
    marker = f"{prefix}_"
    for value in rows:
        if not isinstance(value, str) or not value.startswith(marker):
            continue
        suffix = value[len(marker):]
        if suffix.isdigit():
            max_seen = max(max_seen, int(suffix))
    counters[counter_key] = max_seen + 1
    return f"{prefix}_{counters[counter_key]:08d}"


# ---------------------------------------------------------------------------
# Shared corpus tables
# ---------------------------------------------------------------------------


class Article(Base):
    __tablename__ = "articles"

    id = Column("article_id", String, primary_key=True)
    canonical_uri = Column(String, nullable=True, unique=True)
    filename = Column("primary_title", String, nullable=False)
    language = Column(String, nullable=True)
    filetype = Column("document_type", String, nullable=True)
    publication_date = Column(Date, nullable=True)
    current_text_version_id = Column(
        String,
        ForeignKey(
            "text_versions.text_version_id",
            use_alter=True,
            name="fk_articles_current_text_version",
        ),
        nullable=True,
        index=True,
    )
    legacy_document_id = Column(String, nullable=True, unique=True, index=True)
    uploaded_at = Column("created_at", DateTime, default=_now, nullable=False)

    text_versions = relationship(
        "TextVersion",
        back_populates="article",
        cascade="all, delete-orphan",
        foreign_keys="TextVersion.article_id",
    )
    current_text_version = relationship(
        "TextVersion",
        foreign_keys=[current_text_version_id],
        post_update=True,
    )
    entity_profile_links = relationship(
        "EntityExtractionArticle",
        back_populates="article",
        cascade="all, delete-orphan",
    )
    coreference_chains = relationship("CoreferenceChain", back_populates="document", cascade="all, delete-orphan")
    topic_keywords = relationship("TopicKeyword", back_populates="article", cascade="all, delete-orphan")

    @property
    def content_text(self) -> str:
        tv = self.current_text_version
        return tv.normalized_text if tv and tv.normalized_text is not None else ""

    @content_text.setter
    def content_text(self, value: str) -> None:
        tv = self.current_text_version
        if tv is not None:
            tv.normalized_text = value


class TextVersion(Base):
    __tablename__ = "text_versions"

    id = Column("text_version_id", String, primary_key=True)
    article_id = Column(String, ForeignKey("articles.article_id"), nullable=False, index=True)
    sha256_raw_text = Column(String, nullable=True)
    sha256_normalized_text = Column(String, nullable=True)
    raw_text_path = Column(String, nullable=True)
    normalized_text_path = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    normalized_text = Column(Text, nullable=False)
    normalization_method = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    legacy_document_id = Column(String, nullable=True, index=True)

    article = relationship("Article", back_populates="text_versions", foreign_keys=[article_id])
    processing_runs = relationship("ProcessingRun", back_populates="text_version", cascade="all, delete-orphan")
    span_annotations = relationship("SpanAnnotation", back_populates="text_version", cascade="all, delete-orphan")


class MetadataRecord(Base):
    __tablename__ = "metadata_records"

    id = Column("metadata_id", String, primary_key=True)
    article_id = Column(String, ForeignKey("articles.article_id"), nullable=False, index=True)
    format = Column(String, nullable=False)
    data_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)


class SourceFile(Base):
    __tablename__ = "source_files"

    id = Column("source_file_id", String, primary_key=True)
    article_id = Column(String, ForeignKey("articles.article_id"), nullable=True, index=True)
    text_version_id = Column(String, ForeignKey("text_versions.text_version_id"), nullable=True, index=True)
    source_type = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    original_filename = Column(String, nullable=True)
    storage_path = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    sha256_file = Column(String, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)

    article = relationship("Article")
    text_version = relationship("TextVersion")


class TextSegment(Base):
    __tablename__ = "text_segments"

    id = Column("segment_id", String, primary_key=True)
    text_version_id = Column(String, ForeignKey("text_versions.text_version_id"), nullable=False, index=True)
    segment_type = Column(String, nullable=False)
    parent_segment_id = Column(String, ForeignKey("text_segments.segment_id"), nullable=True)
    ordinal = Column(Integer, nullable=True)
    heading = Column(String, nullable=True)
    start_char = Column(Integer, nullable=False)
    end_char = Column(Integer, nullable=False)
    exact_text = Column(Text, nullable=False)


# ---------------------------------------------------------------------------
# Component provenance and shared annotations
# ---------------------------------------------------------------------------


class NLPComponent(Base):
    __tablename__ = "nlp_components"

    id = Column("component_id", String, primary_key=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    processing_runs = relationship("ProcessingRun", back_populates="component")


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    id = Column("processing_run_id", String, primary_key=True)
    component_id = Column(String, ForeignKey("nlp_components.component_id"), nullable=False, index=True)
    text_version_id = Column(String, ForeignKey("text_versions.text_version_id"), nullable=False, index=True)
    profile_id = Column(String, ForeignKey("entity_extraction_profiles.profile_id"), nullable=True, index=True)
    tool_name = Column(String, nullable=False)
    model_name = Column(String, nullable=True)
    model_version = Column(String, nullable=True)
    parameters_json = Column(Text, nullable=False, default="{}")
    status = Column(String, nullable=False, default="completed")
    started_at = Column(DateTime, default=_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    component = relationship("NLPComponent", back_populates="processing_runs")
    text_version = relationship("TextVersion", back_populates="processing_runs")
    profile = relationship("EntityExtractionProfile")
    span_annotations = relationship("SpanAnnotation", back_populates="processing_run", cascade="all, delete-orphan")


class SpanAnnotation(Base):
    __tablename__ = "span_annotations"

    id = Column("annotation_id", String, primary_key=True)
    processing_run_id = Column(String, ForeignKey("processing_runs.processing_run_id"), nullable=False, index=True)
    text_version_id = Column(String, ForeignKey("text_versions.text_version_id"), nullable=False, index=True)
    annotation_type = Column(String, nullable=False)
    start_char = Column(Integer, nullable=False)
    end_char = Column(Integer, nullable=False)
    exact_text = Column(Text, nullable=False)
    motivation = Column(String, nullable=True)
    body_json = Column(Text, nullable=False, default="{}")
    confidence = Column(Float, nullable=True)
    legacy_mention_id = Column(String, nullable=True, index=True)

    processing_run = relationship("ProcessingRun", back_populates="span_annotations")
    text_version = relationship("TextVersion", back_populates="span_annotations")
    entity_mentions = relationship("EntityMention", back_populates="annotation", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Canonical entities and entity component tables
# ---------------------------------------------------------------------------


class CanonicalEntity(Base):
    __tablename__ = "canonical_entities"

    id = Column("entity_id", String, primary_key=True)
    local_uri = Column(String, nullable=True, unique=True)
    canonical_name = Column("preferred_label", String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)
    ontology_class_uri = Column(String, nullable=True)
    ontology_individual_uri = Column(String, nullable=True)
    wikidata_uri = Column(String, nullable=True)
    dbpedia_uri = Column(String, nullable=True)
    worldcat_uri = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    review_status = Column(String, nullable=False, default="machine_generated", index=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    legacy_entity_id = Column(String, nullable=True, unique=True, index=True)

    mentions = relationship("EntityMention", back_populates="entity", cascade="all, delete-orphan")
    aliases = relationship("EntityAlias", back_populates="entity", cascade="all, delete-orphan")
    profile_links = relationship("EntityExtractionEntity", back_populates="entity", cascade="all, delete-orphan")
    coreference_chains = relationship("CoreferenceChain", back_populates="entity")
    enrichment_properties = relationship("EnrichmentProperty", back_populates="entity", cascade="all, delete-orphan")
    grounding_candidates = relationship("EntityGroundingCandidate", cascade="all, delete-orphan")
    source_reconciliation_events = relationship(
        "EntityReconciliationEvent",
        foreign_keys="EntityReconciliationEvent.source_entity_id",
        back_populates="source_entity",
    )
    target_reconciliation_events = relationship(
        "EntityReconciliationEvent",
        foreign_keys="EntityReconciliationEvent.target_entity_id",
        back_populates="target_entity",
    )


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (UniqueConstraint("entity_id", "alias", "language_code", name="uq_entity_alias"),)

    id = Column("alias_id", String, primary_key=True)
    entity_id = Column(String, ForeignKey("canonical_entities.entity_id"), nullable=False, index=True)
    alias = Column(String, nullable=False, index=True)
    language_code = Column(String, nullable=True)
    source = Column(String, nullable=True)

    entity = relationship("CanonicalEntity", back_populates="aliases")


class EntityMention(Base):
    __tablename__ = "entity_mentions"

    id = Column("mention_id", String, primary_key=True)
    annotation_id = Column(String, ForeignKey("span_annotations.annotation_id"), nullable=False, index=True)
    entity_id = Column(String, ForeignKey("canonical_entities.entity_id"), nullable=False, index=True)
    surface_form = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    linking_method = Column(String, nullable=True)
    review_status = Column(String, nullable=False, default="machine_generated", index=True)
    legacy_mention_id = Column(String, nullable=True, unique=True, index=True)

    annotation = relationship("SpanAnnotation", back_populates="entity_mentions")
    entity = relationship("CanonicalEntity", back_populates="mentions")
    link_candidates = relationship("EntityLinkCandidate", back_populates="mention", cascade="all, delete-orphan")

    document_id = column_property(
        select(TextVersion.article_id)
        .where(TextVersion.id == SpanAnnotation.text_version_id)
        .where(SpanAnnotation.id == annotation_id)
        .correlate_except(TextVersion, SpanAnnotation)
        .scalar_subquery()
    )
    start_char = column_property(
        select(SpanAnnotation.start_char)
        .where(SpanAnnotation.id == annotation_id)
        .correlate_except(SpanAnnotation)
        .scalar_subquery()
    )
    end_char = column_property(
        select(SpanAnnotation.end_char)
        .where(SpanAnnotation.id == annotation_id)
        .correlate_except(SpanAnnotation)
        .scalar_subquery()
    )
    sentence = column_property(
        select(SpanAnnotation.body_json)
        .where(SpanAnnotation.id == annotation_id)
        .correlate_except(SpanAnnotation)
        .scalar_subquery()
    )

    @property
    def document(self) -> Article | None:
        if not self.annotation or not self.annotation.text_version:
            return None
        return self.annotation.text_version.article


class EntityLinkCandidate(Base):
    __tablename__ = "entity_link_candidates"

    id = Column("candidate_id", String, primary_key=True)
    mention_id = Column(String, ForeignKey("entity_mentions.mention_id"), nullable=False, index=True)
    candidate_uri = Column(String, nullable=False)
    wikidata_qid = Column(String, nullable=True)
    label = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    rank = Column(Integer, nullable=True)
    score = Column(Float, nullable=True)
    review_status = Column(String, nullable=False, default="machine_generated", index=True)
    raw_candidate = Column(Text, nullable=True)

    mention = relationship("EntityMention", back_populates="link_candidates")


class EntityGroundingCandidate(Base):
    __tablename__ = "entity_grounding_candidates"
    __table_args__ = (UniqueConstraint("entity_id", "candidate_uri", name="uq_entity_grounding_candidate"),)

    id = Column("grounding_candidate_id", String, primary_key=True)
    entity_id = Column(String, ForeignKey("canonical_entities.entity_id"), nullable=False, index=True)
    candidate_uri = Column(String, nullable=False)
    authority = Column(String, nullable=False)
    label = Column(String, nullable=True)
    score = Column(Float, nullable=True)
    review_status = Column(String, nullable=False, default="machine_generated", index=True)
    raw_candidate = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class EnrichmentProperty(Base):
    __tablename__ = "enrichment_properties"

    id = Column("property_id", String, primary_key=True)
    entity_id = Column(String, ForeignKey("canonical_entities.entity_id"), nullable=False, index=True)
    property_name = Column(String, nullable=False)
    property_uri = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    review_status = Column(String, nullable=False, default="machine_generated", index=True)
    imported_at = Column(DateTime, default=_now, nullable=False)
    legacy_property_id = Column(String, nullable=True, unique=True, index=True)

    entity = relationship("CanonicalEntity", back_populates="enrichment_properties")


# ---------------------------------------------------------------------------
# Entity Manager component settings and scopes
# ---------------------------------------------------------------------------


class EntityExtractionProfile(Base):
    __tablename__ = "entity_extraction_profiles"

    id = Column("profile_id", String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    allowed_types = Column(Text, nullable=False, default="[]")
    is_default = Column(Boolean, nullable=False, default=False)
    component_scope = Column(String, nullable=False, default="entity_manager", index=True)
    parameters_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=_now, nullable=False)
    legacy_profile_id = Column(String, nullable=True, unique=True, index=True)


class EntityExtractionArticle(Base):
    __tablename__ = "entity_extraction_articles"
    __table_args__ = (UniqueConstraint("article_id", "profile_id", name="uq_entity_extraction_article"),)

    id = Column("article_profile_id", String, primary_key=True)
    article_id = Column(String, ForeignKey("articles.article_id"), nullable=False, index=True)
    profile_id = Column(String, ForeignKey("entity_extraction_profiles.profile_id"), nullable=False, index=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    article = relationship("Article", back_populates="entity_profile_links")
    profile = relationship("EntityExtractionProfile")


class EntityExtractionEntity(Base):
    __tablename__ = "entity_extraction_entities"
    __table_args__ = (UniqueConstraint("entity_id", "profile_id", name="uq_entity_extraction_entity"),)

    id = Column("entity_profile_id", String, primary_key=True)
    entity_id = Column(String, ForeignKey("canonical_entities.entity_id"), nullable=False, index=True)
    profile_id = Column(String, ForeignKey("entity_extraction_profiles.profile_id"), nullable=False, index=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    entity = relationship("CanonicalEntity", back_populates="profile_links")
    profile = relationship("EntityExtractionProfile")


class OntologyMapping(Base):
    __tablename__ = "ontology_mappings"

    id = Column("mapping_id", String, primary_key=True)
    spacy_label = Column(String, nullable=False, unique=True)
    ontology_class_uri = Column(String, nullable=False)
    ontology_class_label = Column(String, nullable=True)
    review_status = Column(String, nullable=False, default="machine_generated", index=True)


class EntityReconciliationEvent(Base):
    __tablename__ = "entity_reconciliation_events"

    id = Column("event_id", String, primary_key=True)
    source_entity_id = Column(String, ForeignKey("canonical_entities.entity_id"), nullable=True, index=True)
    target_entity_id = Column(String, ForeignKey("canonical_entities.entity_id"), nullable=True, index=True)
    action = Column(String, nullable=False, default="merge")
    actor = Column(String, nullable=False, default="entity_manager")
    transferred_mentions = Column(Integer, nullable=False, default=0)
    transferred_aliases = Column(Integer, nullable=False, default=0)
    transferred_enrichments = Column(Integer, nullable=False, default=0)
    details_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=_now, nullable=False)

    source_entity = relationship(
        "CanonicalEntity",
        foreign_keys=[source_entity_id],
        back_populates="source_reconciliation_events",
    )
    target_entity = relationship(
        "CanonicalEntity",
        foreign_keys=[target_entity_id],
        back_populates="target_reconciliation_events",
    )


# ---------------------------------------------------------------------------
# TopicManager-owned tables
# ---------------------------------------------------------------------------


class TopicKeyword(Base):
    __tablename__ = "topic_keywords"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "text_version_id",
            "normalized_form",
            name="uq_topic_keyword_text_version_form",
        ),
    )

    id = Column("keyword_id", String, primary_key=True)
    article_id = Column(String, ForeignKey("articles.article_id"), nullable=False, index=True)
    text_version_id = Column(String, ForeignKey("text_versions.text_version_id"), nullable=False, index=True)
    processing_run_id = Column(String, ForeignKey("processing_runs.processing_run_id"), nullable=True, index=True)
    surface_form = Column(String, nullable=False, index=True)
    normalized_form = Column(String, nullable=False, index=True)
    start_char = Column(Integer, nullable=True)
    end_char = Column(Integer, nullable=True)
    extraction_method = Column(String, nullable=False)
    score = Column(Float, nullable=True)
    review_status = Column(String, nullable=False, default="machine_generated", index=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    article = relationship("Article", back_populates="topic_keywords")
    text_version = relationship("TextVersion")
    processing_run = relationship("ProcessingRun")
    candidates = relationship("KeywordFastCandidate", back_populates="keyword", cascade="all, delete-orphan")
    assignments = relationship("KeywordFastAssignment", back_populates="keyword", cascade="all, delete-orphan")


class FastSubject(Base):
    __tablename__ = "fast_subjects"

    id = Column("fast_subject_id", String, primary_key=True)
    fast_id = Column(String, nullable=False, unique=True, index=True)
    uri = Column(String, nullable=False, unique=True)
    authorized_heading = Column(String, nullable=False, index=True)
    facet = Column(String, nullable=True, index=True)
    tag = Column(String, nullable=True)
    raw_payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=_now, nullable=False)

    candidates = relationship("KeywordFastCandidate", back_populates="fast_subject")
    assignments = relationship("KeywordFastAssignment", back_populates="fast_subject")
    schema_memberships = relationship("FastSubjectSchemaMembership", back_populates="fast_subject", cascade="all, delete-orphan")


class KeywordFastCandidate(Base):
    __tablename__ = "keyword_fast_candidates"
    __table_args__ = (
        UniqueConstraint("keyword_id", "fast_subject_id", "query_text", name="uq_keyword_fast_candidate_query"),
    )

    id = Column("candidate_id", String, primary_key=True)
    keyword_id = Column(String, ForeignKey("topic_keywords.keyword_id"), nullable=False, index=True)
    fast_subject_id = Column(String, ForeignKey("fast_subjects.fast_subject_id"), nullable=False, index=True)
    query_text = Column(String, nullable=False)
    rank = Column(Integer, nullable=True)
    lexical_score = Column(Float, nullable=True)
    rank_score = Column(Float, nullable=True)
    context_score = Column(Float, nullable=True)
    combined_score = Column(Float, nullable=True)
    review_status = Column(String, nullable=False, default="machine_generated", index=True)
    raw_candidate_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=_now, nullable=False)

    keyword = relationship("TopicKeyword", back_populates="candidates")
    fast_subject = relationship("FastSubject", back_populates="candidates")


class KeywordFastAssignment(Base):
    __tablename__ = "keyword_fast_assignments"

    id = Column("assignment_id", String, primary_key=True)
    keyword_id = Column(String, ForeignKey("topic_keywords.keyword_id"), nullable=False, index=True)
    fast_subject_id = Column(String, ForeignKey("fast_subjects.fast_subject_id"), nullable=True, index=True)
    status = Column(String, nullable=False, default="accepted", index=True)
    assignment_method = Column(String, nullable=False, default="review")
    query_text = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    keyword = relationship("TopicKeyword", back_populates="assignments")
    fast_subject = relationship("FastSubject", back_populates="assignments")


class TopicSchema(Base):
    __tablename__ = "topic_schemas"

    id = Column("schema_id", String, primary_key=True)
    label = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    schema_type = Column(String, nullable=False, default="topic", index=True)
    review_status = Column(String, nullable=False, default="accepted", index=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    memberships = relationship("FastSubjectSchemaMembership", back_populates="schema", cascade="all, delete-orphan")


class FastSubjectSchemaMembership(Base):
    __tablename__ = "fast_subject_schema_memberships"
    __table_args__ = (
        UniqueConstraint("fast_subject_id", "schema_id", name="uq_fast_subject_schema"),
    )

    id = Column("membership_id", String, primary_key=True)
    fast_subject_id = Column(String, ForeignKey("fast_subjects.fast_subject_id"), nullable=False, index=True)
    schema_id = Column(String, ForeignKey("topic_schemas.schema_id"), nullable=False, index=True)
    review_status = Column(String, nullable=False, default="accepted", index=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    fast_subject = relationship("FastSubject", back_populates="schema_memberships")
    schema = relationship("TopicSchema", back_populates="memberships")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


# ---------------------------------------------------------------------------
# Existing coreference UI support
# ---------------------------------------------------------------------------


class CoreferenceChain(Base):
    __tablename__ = "coreference_chains"

    id = Column("chain_id", String, primary_key=True)
    document_id = Column("article_id", String, ForeignKey("articles.article_id"), nullable=False, index=True)
    entity_id = Column(String, ForeignKey("canonical_entities.entity_id"), nullable=True, index=True)
    processing_run_id = Column(String, ForeignKey("processing_runs.processing_run_id"), nullable=True)
    chain_index = Column(Integer, nullable=False)

    document = relationship("Article", back_populates="coreference_chains")
    entity = relationship("CanonicalEntity", back_populates="coreference_chains")
    members = relationship("CoreferenceMember", back_populates="chain", cascade="all, delete-orphan")


class CoreferenceMember(Base):
    __tablename__ = "coreference_members"

    id = Column("member_id", String, primary_key=True)
    chain_id = Column(String, ForeignKey("coreference_chains.chain_id"), nullable=False, index=True)
    surface_form = Column(String, nullable=False)
    start_char = Column(Integer, nullable=False)
    end_char = Column(Integer, nullable=False)

    chain = relationship("CoreferenceChain", back_populates="members")


# Compatibility names used by the existing routers/services.
Document = Article
Entity = CanonicalEntity
Mention = EntityMention
ExtractionProfile = EntityExtractionProfile


Article.profile_id = column_property(
    select(EntityExtractionArticle.profile_id)
    .where(EntityExtractionArticle.article_id == Article.id)
    .limit(1)
    .correlate_except(EntityExtractionArticle)
    .scalar_subquery()
)
CanonicalEntity.profile_id = column_property(
    select(EntityExtractionEntity.profile_id)
    .where(EntityExtractionEntity.entity_id == CanonicalEntity.id)
    .limit(1)
    .correlate_except(EntityExtractionEntity)
    .scalar_subquery()
)


def _register_prefixed_id(model: type[Base], column_name: str, prefix: str) -> None:
    @event.listens_for(model, "before_insert")
    def _set_id(mapper: Any, connection: Any, target: Any) -> None:
        if getattr(target, column_name) is None:
            db_column_name = mapper.get_property(column_name).columns[0].name
            setattr(target, column_name, _next_prefixed_id(connection, model.__table__, db_column_name, prefix))


for _model, _attr, _prefix in [
    (Article, "id", "art"),
    (TextVersion, "id", "tv"),
    (MetadataRecord, "id", "meta"),
    (SourceFile, "id", "src"),
    (TextSegment, "id", "seg"),
    (NLPComponent, "id", "comp"),
    (ProcessingRun, "id", "run"),
    (SpanAnnotation, "id", "ann"),
    (CanonicalEntity, "id", "ent"),
    (EntityAlias, "id", "alias"),
    (EntityMention, "id", "men"),
    (EntityLinkCandidate, "id", "cand"),
    (EntityGroundingCandidate, "id", "groundcand"),
    (EnrichmentProperty, "id", "prop"),
    (EntityExtractionProfile, "id", "prof"),
    (EntityExtractionArticle, "id", "artprof"),
    (EntityExtractionEntity, "id", "entprof"),
    (OntologyMapping, "id", "map"),
    (CoreferenceChain, "id", "coref"),
    (CoreferenceMember, "id", "corefm"),
    (EntityReconciliationEvent, "id", "recon"),
    (TopicKeyword, "id", "kw"),
    (FastSubject, "id", "fast"),
    (KeywordFastCandidate, "id", "kfc"),
    (KeywordFastAssignment, "id", "kfa"),
    (TopicSchema, "id", "schema"),
    (FastSubjectSchemaMembership, "id", "fsm"),
]:
    _register_prefixed_id(_model, _attr, _prefix)


def ensure_entity_aliases(entity: CanonicalEntity, labels: list[str], source: str = "manual") -> None:
    """Replace an entity's alias collection with a clean de-duplicated set."""
    canonical = entity.canonical_name
    seen: set[str] = set()
    cleaned: list[str] = []
    for label in labels:
        value = str(label).strip()
        if not value or value == canonical or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)

    entity.aliases[:] = [
        EntityAlias(entity_id=entity.id, alias=value, source=source)
        for value in cleaned
    ]


def entity_alias_labels(entity: CanonicalEntity) -> list[str]:
    return [alias.alias for alias in entity.aliases if alias.alias]


def ensure_entity_profile(db, entity: CanonicalEntity, profile_id: str | None) -> None:
    if not profile_id:
        return
    exists = (
        db.query(EntityExtractionEntity)
        .filter(
            EntityExtractionEntity.entity_id == entity.id,
            EntityExtractionEntity.profile_id == profile_id,
        )
        .first()
    )
    if not exists:
        db.add(EntityExtractionEntity(entity_id=entity.id, profile_id=profile_id))


def ensure_article_profile(db, article: Article, profile_id: str | None) -> None:
    if not profile_id:
        return
    exists = (
        db.query(EntityExtractionArticle)
        .filter(
            EntityExtractionArticle.article_id == article.id,
            EntityExtractionArticle.profile_id == profile_id,
        )
        .first()
    )
    if not exists:
        db.add(EntityExtractionArticle(article_id=article.id, profile_id=profile_id))


def get_or_create_component(db, slug: str = "entity_manager", name: str = "EIAS Entity Manager") -> NLPComponent:
    component = db.query(NLPComponent).filter(NLPComponent.slug == slug).first()
    if component:
        return component
    component = NLPComponent(slug=slug, name=name)
    db.add(component)
    db.flush()
    return component
