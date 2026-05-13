"""Entity grounding against Wikidata."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.config import WIKIDATA_API_URL, WIKIDATA_SPARQL_URL, HTTP_HEADERS

logger = logging.getLogger(__name__)

WIKIDATA_ENTITY_URL = "https://www.wikidata.org/entity"


async def search_wikidata(
    query: str,
    entity_type: str | None = None,
    limit: int = 5,
    timeout: int = 15,
    type_filter_enabled: bool = True,
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

    async with httpx.AsyncClient(timeout=timeout, headers=HTTP_HEADERS) as client:
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
    if type_filter_enabled and entity_type and candidates:
        candidates = await _filter_by_type(candidates, entity_type, timeout=timeout)

    return candidates


async def _filter_by_type(
    candidates: list[dict[str, Any]],
    entity_type: str,
    timeout: int = 15,
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
        async with httpx.AsyncClient(timeout=timeout, headers=HTTP_HEADERS) as client:
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
    """Fetch available properties for a Wikidata entity.

    Returns list of dicts with: property_uri, property_name, value.
    """
    entity = await fetch_wikidata_entity(qid, props="claims")
    return await claims_to_properties(entity)


async def fetch_wikidata_entity(qid: str, props: str = "claims|sitelinks") -> dict[str, Any]:
    """Fetch one Wikidata entity from the regular API.

    The query service is aggressively rate-limited during outages; claim reads
    through wbgetentities are enough for local enrichment and are more reliable.
    """
    if not _is_wikidata_id(qid, "Q"):
        return {}

    params = {
        "action": "wbgetentities",
        "ids": qid,
        "props": props,
        "languages": "en",
        "sitefilter": "enwiki",
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=20, headers=HTTP_HEADERS) as client:
        resp = await client.get(WIKIDATA_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    entity = data.get("entities", {}).get(qid, {})
    if entity.get("missing"):
        return {}
    return entity


async def claims_to_properties(
    entity: dict[str, Any],
    property_ids: list[str] | None = None,
    limit: int = 200,
) -> list[dict[str, str]]:
    """Convert wbgetentities claims into local enrichment property dicts."""
    claims = entity.get("claims", {}) if entity else {}
    selected = set(property_ids or [])
    prop_ids = [
        pid for pid in claims
        if _is_wikidata_id(pid, "P") and (not selected or pid in selected)
    ]
    if not prop_ids:
        return []

    label_ids = set(prop_ids)
    for pid in prop_ids:
        for claim in claims.get(pid, []):
            label_ids.update(_linked_entity_ids_from_claim(claim))

    labels = await fetch_wikidata_labels(sorted(label_ids))
    properties: list[dict[str, str]] = []
    for pid in prop_ids:
        for claim in claims.get(pid, []):
            if len(properties) >= limit:
                return properties
            value = _claim_display_value(claim, labels)
            if not value:
                continue
            properties.append({
                "property_uri": f"{WIKIDATA_ENTITY_URL}/{pid}",
                "property_name": labels.get(pid, pid),
                "property_id": pid,
                "value": value,
                "source": "wikidata",
            })

    return properties


async def fetch_wikidata_labels(ids: list[str]) -> dict[str, str]:
    """Return English labels for Wikidata item/property ids."""
    cleaned: list[str] = []
    for entity_id in ids:
        if _is_wikidata_id(entity_id, "Q") or _is_wikidata_id(entity_id, "P"):
            if entity_id not in cleaned:
                cleaned.append(entity_id)

    labels: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=20, headers=HTTP_HEADERS) as client:
        for start in range(0, len(cleaned), 50):
            chunk = cleaned[start:start + 50]
            if not chunk:
                continue
            resp = await client.get(
                WIKIDATA_API_URL,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(chunk),
                    "props": "labels",
                    "languages": "en",
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            for entity_id, entity in data.get("entities", {}).items():
                label = entity.get("labels", {}).get("en", {}).get("value")
                if label:
                    labels[entity_id] = label

    return labels


def first_claim_value(entity: dict[str, Any], property_id: str) -> Any:
    """Return the raw datavalue value for the first claim on a property."""
    claims = entity.get("claims", {}) if entity else {}
    for claim in claims.get(property_id, []):
        datavalue = claim.get("mainsnak", {}).get("datavalue")
        if datavalue and "value" in datavalue:
            return datavalue["value"]
    return None


def wikidata_commons_file_url(filename: str) -> str:
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename)}"


def _is_wikidata_id(value: str, prefix: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(prefix)
        and value[len(prefix):].isdigit()
    )


def _linked_entity_ids_from_claim(claim: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    datavalue = claim.get("mainsnak", {}).get("datavalue") or {}
    value = datavalue.get("value")
    if datavalue.get("type") == "wikibase-entityid" and isinstance(value, dict):
        entity_id = value.get("id")
        if entity_id:
            ids.add(entity_id)
    if datavalue.get("type") == "quantity" and isinstance(value, dict):
        unit = str(value.get("unit", ""))
        unit_id = unit.rstrip("/").split("/")[-1]
        if _is_wikidata_id(unit_id, "Q"):
            ids.add(unit_id)
    return ids


def _claim_display_value(claim: dict[str, Any], labels: dict[str, str]) -> str:
    mainsnak = claim.get("mainsnak", {})
    if mainsnak.get("snaktype") != "value":
        return ""

    datavalue = mainsnak.get("datavalue") or {}
    value = datavalue.get("value")
    value_type = datavalue.get("type")

    if value_type == "wikibase-entityid" and isinstance(value, dict):
        entity_id = value.get("id") or _entity_id_from_numeric(value)
        return labels.get(entity_id, entity_id)

    if value_type == "time" and isinstance(value, dict):
        return _format_wikidata_time(value)

    if value_type == "quantity" and isinstance(value, dict):
        amount = str(value.get("amount", "")).lstrip("+")
        unit = str(value.get("unit", ""))
        unit_id = unit.rstrip("/").split("/")[-1]
        unit_label = labels.get(unit_id, "") if _is_wikidata_id(unit_id, "Q") else ""
        return f"{amount} {unit_label}".strip()

    if value_type == "globecoordinate" and isinstance(value, dict):
        lat = value.get("latitude")
        lon = value.get("longitude")
        return f"{lat}, {lon}" if lat is not None and lon is not None else ""

    if value_type == "monolingualtext" and isinstance(value, dict):
        return str(value.get("text", ""))

    if isinstance(value, str):
        return value

    if value is None:
        return ""
    return str(value)


def _entity_id_from_numeric(value: dict[str, Any]) -> str:
    entity_type = value.get("entity-type")
    numeric_id = value.get("numeric-id")
    if entity_type == "property" and numeric_id:
        return f"P{numeric_id}"
    if numeric_id:
        return f"Q{numeric_id}"
    return ""


def _format_wikidata_time(value: dict[str, Any]) -> str:
    raw = str(value.get("time", ""))
    precision = value.get("precision")
    if not raw:
        return ""

    sign = "-" if raw.startswith("-") else ""
    raw = raw.lstrip("+").lstrip("-")
    date_part = raw.split("T", 1)[0]
    pieces = date_part.split("-")
    if not pieces:
        return ""

    year = sign + pieces[0].lstrip("0") if pieces[0].lstrip("0") else "0"
    month = pieces[1] if len(pieces) > 1 else "00"
    day = pieces[2] if len(pieces) > 2 else "00"

    if precision == 9:
        return year
    if precision == 10:
        return f"{year}-{month}"
    if precision == 11:
        return f"{year}-{month}-{day}"
    return date_part
