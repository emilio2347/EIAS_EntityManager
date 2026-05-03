"""Entity grounding against DBpedia."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import DBPEDIA_SPOTLIGHT_URL, DBPEDIA_LOOKUP_URL, DBPEDIA_SPARQL_URL, HTTP_HEADERS

logger = logging.getLogger(__name__)


async def search_dbpedia(
    query: str,
    entity_type: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search DBpedia for entity candidates.

    Uses DBpedia Lookup API for keyword search.
    Returns a list of candidate dicts with: uri, label, description.
    """
    params = {
        "query": query,
        "maxResults": limit,
        "format": "json",
    }

    candidates: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=15, headers=HTTP_HEADERS) as client:
            resp = await client.get(
                DBPEDIA_LOOKUP_URL,
                params=params,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        for doc in data.get("docs", []):
            uri = ""
            if isinstance(doc.get("resource"), list):
                uri = doc["resource"][0] if doc["resource"] else ""
            elif isinstance(doc.get("resource"), str):
                uri = doc["resource"]

            label = ""
            if isinstance(doc.get("label"), list):
                label = doc["label"][0] if doc["label"] else ""
            elif isinstance(doc.get("label"), str):
                label = doc["label"]

            description = ""
            if isinstance(doc.get("comment"), list):
                description = doc["comment"][0] if doc["comment"] else ""
            elif isinstance(doc.get("comment"), str):
                description = doc["comment"]

            if uri:
                candidates.append({
                    "source": "dbpedia",
                    "uri": uri,
                    "label": label,
                    "description": description[:300] if description else "",
                })

    except Exception as e:
        logger.warning("DBpedia Lookup failed: %s", e)

    # Fallback: try Spotlight for disambiguation if lookup returned nothing
    if not candidates:
        candidates = await _spotlight_annotate(query)

    return candidates[:limit]


async def _spotlight_annotate(text: str) -> list[dict[str, Any]]:
    """Use DBpedia Spotlight to annotate/disambiguate text."""
    candidates: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=15, headers=HTTP_HEADERS) as client:
            resp = await client.post(
                DBPEDIA_SPOTLIGHT_URL,
                data={"text": text, "confidence": "0.35"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        for resource in data.get("Resources", []):
            candidates.append({
                "source": "dbpedia",
                "uri": resource.get("@URI", ""),
                "label": resource.get("@surfaceForm", ""),
                "description": f"Types: {resource.get('@types', '')}",
            })

    except Exception as e:
        logger.warning("DBpedia Spotlight failed: %s", e)

    return candidates


async def get_entity_properties(dbpedia_uri: str) -> list[dict[str, Any]]:
    """Fetch available properties for a DBpedia entity via SPARQL.

    Returns list of dicts with: property_uri, property_name, value.
    """
    sparql = f"""
    SELECT ?prop ?value WHERE {{
        <{dbpedia_uri}> ?prop ?value .
        FILTER(isLiteral(?value) && langMatches(lang(?value), "en"))
    }}
    LIMIT 100
    """

    properties: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=20, headers=HTTP_HEADERS) as client:
            resp = await client.get(
                DBPEDIA_SPARQL_URL,
                params={"query": sparql, "format": "json"},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            data = resp.json()

        for binding in data.get("results", {}).get("bindings", []):
            prop_uri = binding.get("prop", {}).get("value", "")
            value = binding.get("value", {}).get("value", "")
            # Extract property name from URI fragment
            prop_name = prop_uri.rsplit("/", 1)[-1] if "/" in prop_uri else prop_uri
            properties.append({
                "property_uri": prop_uri,
                "property_name": prop_name,
                "value": value,
                "source": "dbpedia",
            })

    except Exception as e:
        logger.warning("DBpedia SPARQL failed: %s", e)

    return properties
