"""Ontology management — parse .ttl files and extract classes / individuals."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, RDF, RDFS, OWL, Namespace
from rdflib.term import URIRef

from app.config import ONTOLOGY_DIR


SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


_current_graph: Graph | None = None


def get_ontology_path() -> Path | None:
    """Return path of the currently stored ontology file, or None."""
    files = list(ONTOLOGY_DIR.glob("*.ttl"))
    return files[0] if files else None


def load_ontology(ttl_bytes: bytes, filename: str) -> Path:
    """Persist a .ttl file and parse it into the in-memory graph."""
    global _current_graph

    # Clear old files
    for f in ONTOLOGY_DIR.glob("*.ttl"):
        f.unlink()

    dest = ONTOLOGY_DIR / filename
    dest.write_bytes(ttl_bytes)

    _current_graph = Graph()
    _current_graph.parse(str(dest), format="turtle")
    return dest


def get_graph() -> Graph | None:
    """Return the current in-memory ontology graph, loading from disk if needed."""
    global _current_graph
    if _current_graph is None:
        path = get_ontology_path()
        if path:
            _current_graph = Graph()
            _current_graph.parse(str(path), format="turtle")
    return _current_graph


def extract_classes() -> list[dict[str, Any]]:
    """Extract all owl:Class and rdfs:Class entries from the ontology.

    Returns a list of dicts with keys: uri, label, comment, superclass_uri.
    """
    g = get_graph()
    if g is None:
        return []

    classes: dict[str, dict[str, Any]] = {}

    # Collect owl:Class instances
    for cls in g.subjects(RDF.type, OWL.Class):
        if isinstance(cls, URIRef):
            classes[str(cls)] = _class_info(g, cls)

    # Collect rdfs:Class instances
    for cls in g.subjects(RDF.type, RDFS.Class):
        if isinstance(cls, URIRef) and str(cls) not in classes:
            classes[str(cls)] = _class_info(g, cls)

    # Also collect anything that appears as rdfs:subClassOf subject
    for subj in g.subjects(RDFS.subClassOf, None):
        if isinstance(subj, URIRef) and str(subj) not in classes:
            classes[str(subj)] = _class_info(g, subj)

    return list(classes.values())


def _class_info(g: Graph, cls: URIRef) -> dict[str, Any]:
    """Build info dict for a single class URI."""
    label = None
    for lbl in g.objects(cls, RDFS.label):
        label = str(lbl)
        break

    comment = None
    for cmt in g.objects(cls, RDFS.comment):
        comment = str(cmt)
        break

    superclass = None
    for sup in g.objects(cls, RDFS.subClassOf):
        if isinstance(sup, URIRef):
            superclass = str(sup)
            break

    # Use fragment or last path segment as fallback label
    if label is None:
        frag = cls.fragment if hasattr(cls, 'fragment') else None
        if frag:
            label = str(frag)
        else:
            label = str(cls).rsplit("/", 1)[-1]

    return {
        "uri": str(cls),
        "label": label,
        "comment": comment,
        "superclass_uri": superclass,
    }


def get_ontology_raw() -> str | None:
    """Return the raw .ttl content as a string."""
    path = get_ontology_path()
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return None


def extract_individuals() -> list[dict[str, Any]]:
    """Extract owl:NamedIndividual instances from the ontology.

    Returns a list of dicts with keys: uri, label, types (list of class URIs),
    and pref_label (skos:prefLabel if present).
    """
    g = get_graph()
    if g is None:
        return []

    individuals: dict[str, dict[str, Any]] = {}

    for ind in g.subjects(RDF.type, OWL.NamedIndividual):
        if not isinstance(ind, URIRef):
            continue
        individuals[str(ind)] = _individual_info(g, ind)

    return sorted(individuals.values(), key=lambda x: x["label"].lower())


def _individual_info(g: Graph, ind: URIRef) -> dict[str, Any]:
    """Build info dict for a single NamedIndividual."""
    label = None
    for lbl in g.objects(ind, RDFS.label):
        label = str(lbl)
        break

    if label is None:
        for lbl in g.objects(ind, SKOS.prefLabel):
            label = str(lbl)
            break

    if label is None:
        # Fall back to fragment / final path segment
        s = str(ind)
        if "#" in s:
            label = s.rsplit("#", 1)[-1]
        else:
            label = s.rsplit("/", 1)[-1]
        # Replace underscores for readability
        label = label.replace("_", " ")

    # Collect rdf:type values that aren't owl:NamedIndividual
    types: list[str] = []
    for t in g.objects(ind, RDF.type):
        if isinstance(t, URIRef) and t != OWL.NamedIndividual:
            types.append(str(t))

    return {
        "uri": str(ind),
        "label": label,
        "types": types,
    }


_LOCAL_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def _slugify_local_name(name: str) -> str:
    slug = _LOCAL_NAME_RE.sub("_", name.strip()).strip("_")
    return slug or "Individual"


def add_individual(label: str, class_uri: str | None = None) -> dict[str, Any]:
    """Append a new owl:NamedIndividual to the ontology and persist to disk.

    Returns the new individual's info dict (uri, label, types).
    Raises ValueError if no ontology is loaded.
    """
    g = get_graph()
    path = get_ontology_path()
    if g is None or path is None:
        raise ValueError("No ontology loaded; upload a .ttl file before adding individuals.")

    # Build a URI in the ontology's default namespace (the ":" prefix), or
    # fall back to a generic eias namespace.
    ns_for_new: str | None = None
    for prefix, ns in g.namespaces():
        if prefix == "":
            ns_for_new = str(ns)
            break
    if ns_for_new is None:
        ns_for_new = "https://eias.org/individual/"

    local_name = _slugify_local_name(label)
    candidate_uri = f"{ns_for_new}{local_name}"
    suffix = 1
    while (URIRef(candidate_uri), None, None) in g:
        suffix += 1
        candidate_uri = f"{ns_for_new}{local_name}_{suffix}"

    subj = URIRef(candidate_uri)
    g.add((subj, RDF.type, OWL.NamedIndividual))
    if class_uri:
        g.add((subj, RDF.type, URIRef(class_uri)))
    g.add((subj, RDFS.label, Literal(label)))

    # Persist back to disk in turtle format, preserving the filename.
    g.serialize(destination=str(path), format="turtle")

    return _individual_info(g, subj)
