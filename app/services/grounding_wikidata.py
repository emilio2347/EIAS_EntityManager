"""Entity grounding against Wikidata."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import WIKIDATA_API_URL, WIKIDATA_SPARQL_URL, HTTP_HEADERS

logger = logging.getLogger(__name__)


async def search_wikidata(
    query: str,
    entity_type: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search Wikidata for entity candidates.

    Uses the wbsearchentities API for keyword search.
    Returns a list of candidate dicts with: id, uri, label, description.
    """
    params = {
        "action": "wbsearchentities",
        "search": query,
        "language": "en",
        "format": "json",
        "limit": limit,
        "type": "item",
    }

    async with httpx.AsyncClient(timeout=15, headers=HTTP_HEADERS) as client:
        resp = await client.get(WIKIDATA_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    candidates: list[dict[str, Any]] = []
    for item in data.get("search", []):
        candidates.append({
            "source": "wikidata",
            "id": item["id"],
            "uri": f"https://www.wikidata.org/wiki/{item['id']}",
            "label": item.get("label", ""),
            "description": item.get("description", ""),
            "aliases": [a for a in item.get("aliases", [])],
        })

    # If an entity_type filter is given, try to narrow via SPARQL
    if entity_type and candidates:
        candidates = await _filter_by_type(candidates, entity_type)

    return candidates


async def _filter_by_type(
    candidates: list[dict[str, Any]],
    entity_type: str,
) -> list[dict[str, Any]]:
    """Optionally re-rank candidates using SPARQL type queries.

    Maps common NER types to Wikidata classes for filtering.
    """
    type_map = {
        "PERSON": "Q5",          # human
        "ORG": "Q43229",         # organization
        "GPE": "Q515",           # city (broad)
        "LOC": "Q2221906",       # geographic location
        "WORK_OF_ART": "Q17537576",  # creative work
        "EVENT": "Q1656682",     # event
    }

    wikidata_type = type_map.get(entity_type)
    if not wikidata_type:
        return candidates

    # Check each candidate for instanceof
    filtered = []
    qids = [c["id"] for c in candidates]
    values = " ".join(f"wd:{qid}" for qid in qids)

    sparql = f"""
    SELECT ?item WHERE {{
        VALUES ?item {{ {values} }}
        ?item wdt:P31/wdt:P279* wd:{wikidata_type} .
    }}
    """

    try:
        async with httpx.AsyncClient(timeout=15, headers=HTTP_HEADERS) as client:
            resp = await client.get(
                WIKIDATA_SPARQL_URL,
                params={"query": sparql, "format": "json"},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            results = resp.json()

        matching_uris = set()
        for binding in results.get("results", {}).get("bindings", []):
            matching_uris.add(binding["item"]["value"].split("/")[-1])

        # Put matching candidates first, keep others after
        matched = [c for c in candidates if c["id"] in matching_uris]
        rest = [c for c in candidates if c["id"] not in matching_uris]
        return matched + rest

    except Exception as e:
        logger.warning("SPARQL type filter failed: %s", e)
        return candidates


async def get_entity_properties(qid: str) -> list[dict[str, Any]]:
    """Fetch available properties for a Wikidata entity via SPARQL.

    Returns list of dicts with: property_uri, property_name, value.
    """
    sparql = f"""
    SELECT ?prop ?propLabel ?value ?valueLabel WHERE {{
        wd:{qid} ?p ?statement .
        ?statement ?ps ?value .
        ?prop wikibase:claim ?p .
        ?prop wikibase:statementProperty ?ps .
        SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }}
    LIMIT 100
    """

    async with httpx.AsyncClient(timeout=20, headers=HTTP_HEADERS) as client:
        resp = await client.get(
            WIKIDATA_SPARQL_URL,
            params={"query": sparql, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        data = resp.json()

    properties: list[dict[str, Any]] = []
    for binding in data.get("results", {}).get("bindings", []):
        properties.append({
            "property_uri": binding.get("prop", {}).get("value", ""),
            "property_name": binding.get("propLabel", {}).get("value", ""),
            "value": binding.get("valueLabel", {}).get("value", "")
                     or binding.get("value", {}).get("value", ""),
            "source": "wikidata",
        })

    return properties
