"""SQLAlchemy ORM models for the Entity Manager."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_uuid)
    profile_id = Column(String, ForeignKey("extraction_profiles.id"), nullable=True, index=True)
    filename = Column(String, nullable=False)
    filetype = Column(String, nullable=False)  # txt, md, pdf, json
    content_text = Column(Text, nullable=False)
    uploaded_at = Column(DateTime, default=_now)

    mentions = relationship("Mention", back_populates="document", cascade="all, delete-orphan")
    coreference_chains = relationship("CoreferenceChain", back_populates="document", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

class Entity(Base):
    __tablename__ = "entities"

    id = Column(String, primary_key=True, default=_uuid)
    profile_id = Column(String, ForeignKey("extraction_profiles.id"), nullable=True, index=True)
    canonical_name = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)  # spaCy label: PERSON, ORG, etc.
    alternative_labels = Column(Text, nullable=False, default="[]")  # JSON list of strings
    ontology_class_uri = Column(String, nullable=True)
    ontology_individual_uri = Column(String, nullable=True)
    wikidata_uri = Column(String, nullable=True)
    dbpedia_uri = Column(String, nullable=True)
    worldcat_uri = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)

    mentions = relationship("Mention", back_populates="entity", cascade="all, delete-orphan")
    coreference_chains = relationship("CoreferenceChain", back_populates="entity")
    enrichment_properties = relationship("EnrichmentProperty", back_populates="entity", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Mentions  (entity occurrences in documents)
# ---------------------------------------------------------------------------

class Mention(Base):
    __tablename__ = "mentions"

    id = Column(String, primary_key=True, default=_uuid)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    surface_form = Column(String, nullable=False)
    start_char = Column(Integer, nullable=False)
    end_char = Column(Integer, nullable=False)
    sentence = Column(Text, nullable=True)

    entity = relationship("Entity", back_populates="mentions")
    document = relationship("Document", back_populates="mentions")


# ---------------------------------------------------------------------------
# Coreference
# ---------------------------------------------------------------------------

class CoreferenceChain(Base):
    __tablename__ = "coreference_chains"

    id = Column(String, primary_key=True, default=_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=True)
    chain_index = Column(Integer, nullable=False)

    document = relationship("Document", back_populates="coreference_chains")
    entity = relationship("Entity", back_populates="coreference_chains")
    members = relationship("CoreferenceMember", back_populates="chain", cascade="all, delete-orphan")


class CoreferenceMember(Base):
    __tablename__ = "coreference_members"

    id = Column(String, primary_key=True, default=_uuid)
    chain_id = Column(String, ForeignKey("coreference_chains.id"), nullable=False)
    surface_form = Column(String, nullable=False)
    start_char = Column(Integer, nullable=False)
    end_char = Column(Integer, nullable=False)

    chain = relationship("CoreferenceChain", back_populates="members")


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class EnrichmentProperty(Base):
    __tablename__ = "enrichment_properties"

    id = Column(String, primary_key=True, default=_uuid)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    property_name = Column(String, nullable=False)
    property_uri = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    source = Column(String, nullable=False)  # "wikidata" or "dbpedia"
    imported_at = Column(DateTime, default=_now)

    entity = relationship("Entity", back_populates="enrichment_properties")


# ---------------------------------------------------------------------------
# Ontology mappings  (spaCy NER label → ontology class)
# ---------------------------------------------------------------------------

class OntologyMapping(Base):
    __tablename__ = "ontology_mappings"

    id = Column(String, primary_key=True, default=_uuid)
    spacy_label = Column(String, nullable=False, unique=True)
    ontology_class_uri = Column(String, nullable=False)
    ontology_class_label = Column(String, nullable=True)


# ---------------------------------------------------------------------------
# Extraction Profiles  (per-document NER type filters)
# ---------------------------------------------------------------------------

class ExtractionProfile(Base):
    __tablename__ = "extraction_profiles"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False, unique=True)
    allowed_types = Column(Text, nullable=False, default="[]")  # JSON list of NER labels
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=_now)


# ---------------------------------------------------------------------------
# App Settings  (small JSON-backed configuration values)
# ---------------------------------------------------------------------------

class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
