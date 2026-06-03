"""Export entity database to JSON, CSV, and RDF/XML."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Sequence

from rdflib import Graph, Namespace, Literal, URIRef, RDF, RDFS
from sqlalchemy.orm import Session

from app.models import Entity, Mention, EnrichmentProperty
from app.services.ontology_manager import get_graph


SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
OWL_SAME_AS = URIRef("http://www.w3.org/2002/07/owl#sameAs")


def _entity_alt_labels(entity: Entity) -> list[str]:
    return [alias.alias for alias in entity.aliases if alias.alias]


def _mention_sentence(mention: Mention) -> str | None:
    try:
        data = json.loads(mention.sentence or "")
        if isinstance(data, dict):
            return data.get("sentence")
    except (ValueError, TypeError):
        pass
    return mention.sentence


def _entity_query(db: Session, entity_types: Sequence[str] | None = None):
    query = db.query(Entity)
    normalized_types = [t.strip().upper() for t in entity_types or [] if t and t.strip()]
    if normalized_types:
        query = query.filter(Entity.entity_type.in_(normalized_types))
    return query


def export_json(
    db: Session,
    profile_id: str | None = None,
    entity_types: Sequence[str] | None = None,
    include_enrichments: bool = True,
) -> str:
    """Export all entities as nested JSON."""
    query = _entity_query(db, entity_types)
    entities = query.all()
    data: list[dict[str, Any]] = []

    for ent in entities:
        mentions = db.query(Mention).filter(Mention.entity_id == ent.id).all()
        enrichments = (
            db.query(EnrichmentProperty).filter(EnrichmentProperty.entity_id == ent.id).all()
            if include_enrichments
            else []
        )

        record = {
            "id": ent.id,
            "canonical_name": ent.canonical_name,
            "alternative_labels": _entity_alt_labels(ent),
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
                    "sentence": _mention_sentence(m),
                }
                for m in mentions
            ],
        }
        if include_enrichments:
            record["enrichment"] = [
                {
                    "property_name": ep.property_name,
                    "property_uri": ep.property_uri,
                    "value": ep.value,
                    "source": ep.source,
                }
                for ep in enrichments
            ]
        data.append(record)

    return json.dumps(data, indent=2, ensure_ascii=False)


def export_csv(
    db: Session,
    profile_id: str | None = None,
    entity_types: Sequence[str] | None = None,
    include_enrichments: bool = True,
) -> str:
    """Export all entities as a flat CSV table."""
    query = _entity_query(db, entity_types)
    entities = query.all()
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    header = [
        "id",
        "canonical_name",
        "alternative_labels",
        "entity_type",
        "ontology_class_uri",
        "ontology_individual_uri",
        "wikidata_uri",
        "dbpedia_uri",
        "worldcat_uri",
        "mention_count",
        "created_at",
    ]
    if include_enrichments:
        header.extend(["enrichment_count", "enrichment_json"])
    writer.writerow(header)

    for ent in entities:
        mention_count = db.query(Mention).filter(Mention.entity_id == ent.id).count()
        enrichments = (
            db.query(EnrichmentProperty).filter(EnrichmentProperty.entity_id == ent.id).all()
            if include_enrichments
            else []
        )

        row = [
            ent.id,
            ent.canonical_name,
            "; ".join(_entity_alt_labels(ent)),
            ent.entity_type,
            ent.ontology_class_uri or "",
            ent.ontology_individual_uri or "",
            ent.wikidata_uri or "",
            ent.dbpedia_uri or "",
            ent.worldcat_uri or "",
            mention_count,
            ent.created_at.isoformat() if ent.created_at else "",
        ]
        if include_enrichments:
            row.extend(
                [
                    len(enrichments),
                    json.dumps(
                        [
                            {
                                "property_name": ep.property_name,
                                "property_uri": ep.property_uri,
                                "value": ep.value,
                                "source": ep.source,
                            }
                            for ep in enrichments
                        ],
                        ensure_ascii=False,
                    ),
                ]
            )
        writer.writerow(row)

    return output.getvalue()


def _entity_graph(
    db: Session,
    profile_id: str | None = None,
    entity_types: Sequence[str] | None = None,
    include_enrichments: bool = True,
) -> Graph:
    """Build an RDF graph for all exported entities."""
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

    query = _entity_query(db, entity_types)
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
        # Alternative labels
        for alt in _entity_alt_labels(ent):
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
        if include_enrichments:
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

    return g


def export_rdf_xml(
    db: Session,
    profile_id: str | None = None,
    entity_types: Sequence[str] | None = None,
    include_enrichments: bool = True,
) -> str:
    """Export all entities as RDF/XML using the loaded ontology."""
    return _entity_graph(db, profile_id, entity_types, include_enrichments).serialize(format="xml")


def export_turtle(
    db: Session,
    profile_id: str | None = None,
    entity_types: Sequence[str] | None = None,
    include_enrichments: bool = True,
) -> str:
    """Export all entities as Turtle."""
    return _entity_graph(db, profile_id, entity_types, include_enrichments).serialize(format="turtle")


def export_json_ld(
    db: Session,
    profile_id: str | None = None,
    entity_types: Sequence[str] | None = None,
    include_enrichments: bool = True,
) -> str:
    """Export all entities as JSON-LD."""
    return _entity_graph(db, profile_id, entity_types, include_enrichments).serialize(format="json-ld", indent=2)
