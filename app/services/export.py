"""Export entity database to JSON, CSV, and RDF/XML."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from rdflib import Graph, Namespace, Literal, URIRef, RDF, RDFS
from sqlalchemy.orm import Session

from app.models import Entity, Mention, EnrichmentProperty
from app.services.ontology_manager import get_graph


SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
OWL_SAME_AS = URIRef("http://www.w3.org/2002/07/owl#sameAs")


def _decode_alt_labels(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x) for x in data if x]
    except (ValueError, TypeError):
        pass
    return []


def export_json(db: Session, profile_id: str | None = None) -> str:
    """Export all entities as nested JSON."""
    query = db.query(Entity)
    if profile_id:
        query = query.filter(Entity.profile_id == profile_id)
    entities = query.all()
    data: list[dict[str, Any]] = []

    for ent in entities:
        mentions = db.query(Mention).filter(Mention.entity_id == ent.id).all()
        enrichments = db.query(EnrichmentProperty).filter(
            EnrichmentProperty.entity_id == ent.id
        ).all()

        data.append({
            "id": ent.id,
            "profile_id": ent.profile_id,
            "canonical_name": ent.canonical_name,
            "alternative_labels": _decode_alt_labels(ent.alternative_labels),
            "entity_type": ent.entity_type,
            "ontology_class_uri": ent.ontology_class_uri,
            "ontology_individual_uri": ent.ontology_individual_uri,
            "wikidata_uri": ent.wikidata_uri,
            "dbpedia_uri": ent.dbpedia_uri,
            "worldcat_uri": ent.worldcat_uri,
            "created_at": ent.created_at.isoformat() if ent.created_at else None,
            "mentions": [
                {
                    "document_id": m.document_id,
                    "surface_form": m.surface_form,
                    "start_char": m.start_char,
                    "end_char": m.end_char,
                    "sentence": m.sentence,
                }
                for m in mentions
            ],
            "enrichment": [
                {
                    "property_name": ep.property_name,
                    "property_uri": ep.property_uri,
                    "value": ep.value,
                    "source": ep.source,
                }
                for ep in enrichments
            ],
        })

    return json.dumps(data, indent=2, ensure_ascii=False)


def export_csv(db: Session, profile_id: str | None = None) -> str:
    """Export all entities as a flat CSV table."""
    query = db.query(Entity)
    if profile_id:
        query = query.filter(Entity.profile_id == profile_id)
    entities = query.all()
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "id",
        "profile_id",
        "canonical_name",
        "alternative_labels",
        "entity_type",
        "ontology_class_uri",
        "ontology_individual_uri",
        "wikidata_uri",
        "dbpedia_uri",
        "worldcat_uri",
        "mention_count",
        "enrichment_count",
        "created_at",
    ])

    for ent in entities:
        mention_count = db.query(Mention).filter(Mention.entity_id == ent.id).count()
        enrichment_count = db.query(EnrichmentProperty).filter(
            EnrichmentProperty.entity_id == ent.id
        ).count()

        writer.writerow([
            ent.id,
            ent.profile_id or "",
            ent.canonical_name,
            "; ".join(_decode_alt_labels(ent.alternative_labels)),
            ent.entity_type,
            ent.ontology_class_uri or "",
            ent.ontology_individual_uri or "",
            ent.wikidata_uri or "",
            ent.dbpedia_uri or "",
            ent.worldcat_uri or "",
            mention_count,
            enrichment_count,
            ent.created_at.isoformat() if ent.created_at else "",
        ])

    return output.getvalue()


def export_rdf_xml(db: Session, profile_id: str | None = None) -> str:
    """Export all entities as RDF/XML using the loaded ontology."""
    EIAS = Namespace("http://eias.org/entity/")
    EIAS_PROP = Namespace("http://eias.org/property/")

    g = Graph()
    g.bind("eias", EIAS)
    g.bind("eias_prop", EIAS_PROP)
    g.bind("rdfs", RDFS)
    g.bind("skos", SKOS)

    # Import ontology namespaces if available
    onto_graph = get_graph()
    if onto_graph:
        for prefix, ns in onto_graph.namespaces():
            if prefix:
                g.bind(prefix, ns)

    query = db.query(Entity)
    if profile_id:
        query = query.filter(Entity.profile_id == profile_id)
    entities = query.all()

    for ent in entities:
        subj = EIAS[ent.id]

        # Type assertion
        if ent.ontology_class_uri:
            g.add((subj, RDF.type, URIRef(ent.ontology_class_uri)))

        # Labels
        g.add((subj, RDFS.label, Literal(ent.canonical_name)))
        g.add((subj, SKOS.prefLabel, Literal(ent.canonical_name)))
        g.add((subj, EIAS_PROP["entityType"], Literal(ent.entity_type)))
        if ent.profile_id:
            g.add((subj, EIAS_PROP["profileID"], Literal(ent.profile_id)))

        # Alternative labels
        for alt in _decode_alt_labels(ent.alternative_labels):
            g.add((subj, SKOS.altLabel, Literal(alt)))

        # Linked ontology individual (Particular)
        if ent.ontology_individual_uri:
            g.add((subj, OWL_SAME_AS, URIRef(ent.ontology_individual_uri)))

        # Grounding links
        if ent.wikidata_uri:
            g.add((subj, EIAS_PROP["wikidataURI"], URIRef(ent.wikidata_uri)))
        if ent.dbpedia_uri:
            g.add((subj, EIAS_PROP["dbpediaURI"], URIRef(ent.dbpedia_uri)))
        if ent.worldcat_uri:
            g.add((subj, EIAS_PROP["worldcatURI"], URIRef(ent.worldcat_uri)))

        # Enrichment properties
        enrichments = db.query(EnrichmentProperty).filter(
            EnrichmentProperty.entity_id == ent.id
        ).all()
        for ep in enrichments:
            pred = URIRef(ep.property_uri) if ep.property_uri.startswith("http") else EIAS_PROP[ep.property_name]
            # Check if value is a URI or literal
            if ep.value.startswith("http://") or ep.value.startswith("https://"):
                g.add((subj, pred, URIRef(ep.value)))
            else:
                g.add((subj, pred, Literal(ep.value)))

    return g.serialize(format="xml")
