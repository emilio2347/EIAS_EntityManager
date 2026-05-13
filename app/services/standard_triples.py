"""Standard enrichment triples imported after Wikidata grounding."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote, unquote

import httpx
from sqlalchemy.orm import Session

from app.config import HTTP_HEADERS, WIKIDATA_SPARQL_URL
from app.models import AppSetting, Entity, EnrichmentProperty

logger = logging.getLogger(__name__)

STANDARD_TRIPLES_SETTING_KEY = "standard_triples.enabled_property_ids"

STANDARD_TRIPLE_GROUPS: list[dict[str, Any]] = [
    {
        "source": "wikidata",
        "label": "Wikidata biographical",
        "properties": [
            {"id": "P569", "label": "date of birth"},
            {"id": "P570", "label": "date of death"},
            {"id": "P19", "label": "place of birth"},
            {"id": "P20", "label": "place of death"},
            {"id": "P106", "label": "occupation"},
            {"id": "P27", "label": "country of citizenship"},
            {"id": "P69", "label": "educated at"},
            {"id": "P800", "label": "notable work"},
        ],
    },
    {
        "source": "wikidata",
        "label": "Wikidata organizational",
        "properties": [
            {"id": "P571", "label": "inception"},
            {"id": "P576", "label": "dissolved, abolished or demolished date"},
            {"id": "P159", "label": "headquarters location"},
            {"id": "P112", "label": "founded by"},
            {"id": "P749", "label": "parent organization"},
            {"id": "P856", "label": "official website"},
        ],
    },
    {
        "source": "authority",
        "label": "Authority identifiers from Wikidata",
        "properties": [
            {"id": "P10832", "label": "WorldCat Entities ID"},
            {"id": "P214", "label": "VIAF ID"},
            {"id": "P213", "label": "ISNI"},
            {"id": "P244", "label": "Library of Congress authority ID"},
            {"id": "P268", "label": "Bibliotheque nationale de France ID"},
            {"id": "P227", "label": "GND ID"},
        ],
    },
]

DEFAULT_STANDARD_TRIPLE_IDS = [
    "P569",
    "P570",
    "P19",
    "P20",
    "P106",
    "P27",
    "P10832",
    "P214",
    "P213",
    "P244",
]

_FORMATTERS = {
    "P10832": "https://id.oclc.org/worldcat/entity/{value}",
    "P214": "https://viaf.org/viaf/{value}",
    "P213": "https://isni.org/isni/{value}",
    "P244": "https://id.loc.gov/authorities/names/{value}",
    "P268": "https://catalogue.bnf.fr/ark:/12148/cb{value}",
    "P227": "https://d-nb.info/gnd/{value}",
}


def all_standard_property_ids() -> set[str]:
    ids: set[str] = set()
    for group in STANDARD_TRIPLE_GROUPS:
        ids.update(prop["id"] for prop in group["properties"])
    return ids


def get_enabled_standard_property_ids(db: Session) -> list[str]:
    setting = db.query(AppSetting).filter(AppSetting.key == STANDARD_TRIPLES_SETTING_KEY).first()
    if not setting:
        return list(DEFAULT_STANDARD_TRIPLE_IDS)
    try:
        data = json.loads(setting.value)
    except (TypeError, ValueError):
        return list(DEFAULT_STANDARD_TRIPLE_IDS)
    if not isinstance(data, list):
        return list(DEFAULT_STANDARD_TRIPLE_IDS)

    allowed = all_standard_property_ids()
    return [str(pid) for pid in data if str(pid) in allowed]


def set_enabled_standard_property_ids(db: Session, property_ids: list[str]) -> list[str]:
    allowed = all_standard_property_ids()
    cleaned: list[str] = []
    for prop_id in property_ids:
        prop_id = str(prop_id).strip()
        if prop_id in allowed and prop_id not in cleaned:
            cleaned.append(prop_id)

    setting = db.query(AppSetting).filter(AppSetting.key == STANDARD_TRIPLES_SETTING_KEY).first()
    if setting:
        setting.value = json.dumps(cleaned)
    else:
        setting = AppSetting(key=STANDARD_TRIPLES_SETTING_KEY, value=json.dumps(cleaned))
        db.add(setting)
    db.commit()
    return cleaned


def qid_from_wikidata_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    qid = uri.rstrip("/").split("/")[-1]
    if qid.startswith("Q") and qid[1:].isdigit():
        return qid
    return None


async def resolve_wikidata_external_uris(qid: str) -> dict[str, str]:
    """Resolve other source URIs that can be inferred from a Wikidata item."""
    sparql = f"""
    SELECT ?worldcat ?viaf ?isni ?lccn ?article WHERE {{
        OPTIONAL {{ wd:{qid} wdt:P10832 ?worldcat . }}
        OPTIONAL {{ wd:{qid} wdt:P214 ?viaf . }}
        OPTIONAL {{ wd:{qid} wdt:P213 ?isni . }}
        OPTIONAL {{ wd:{qid} wdt:P244 ?lccn . }}
        OPTIONAL {{
            ?article schema:about wd:{qid} ;
                     schema:isPartOf <https://en.wikipedia.org/> .
        }}
    }}
    LIMIT 1
    """

    async with httpx.AsyncClient(timeout=20, headers=HTTP_HEADERS) as client:
        resp = await client.get(
            WIKIDATA_SPARQL_URL,
            params={"query": sparql, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        data = resp.json()

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return {}

    row = bindings[0]
    uris: dict[str, str] = {}
    worldcat = row.get("worldcat", {}).get("value")
    if worldcat:
        uris["worldcat_uri"] = _FORMATTERS["P10832"].format(value=worldcat)

    article = row.get("article", {}).get("value")
    if article and "/wiki/" in article:
        title = unquote(article.rsplit("/wiki/", 1)[-1])
        if title:
            uris["dbpedia_uri"] = f"https://dbpedia.org/resource/{title}"

    viaf = row.get("viaf", {}).get("value")
    if viaf:
        uris["viaf_uri"] = _FORMATTERS["P214"].format(value=viaf)

    isni = row.get("isni", {}).get("value")
    if isni:
        uris["isni_uri"] = _FORMATTERS["P213"].format(value=isni.replace(" ", ""))

    lccn = row.get("lccn", {}).get("value")
    if lccn:
        uris["loc_uri"] = _FORMATTERS["P244"].format(value=lccn)

    return uris


async def fetch_wikidata_image_url(qid: str) -> str | None:
    """Return a Commons Special:FilePath URL for a Wikidata P18 image."""
    sparql = f"""
    SELECT ?image WHERE {{
        wd:{qid} wdt:P18 ?image .
    }}
    LIMIT 1
    """

    async with httpx.AsyncClient(timeout=20, headers=HTTP_HEADERS) as client:
        resp = await client.get(
            WIKIDATA_SPARQL_URL,
            params={"query": sparql, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        data = resp.json()

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None

    raw = bindings[0].get("image", {}).get("value", "")
    filename = unquote(raw.rsplit("/", 1)[-1]) if raw else ""
    if not filename:
        return None
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename)}"


async def fetch_standard_properties(qid: str, property_ids: list[str]) -> list[dict[str, str]]:
    if not property_ids:
        return []

    values = " ".join(f"wd:{pid}" for pid in property_ids)
    sparql = f"""
    SELECT ?prop ?propLabel ?value ?valueLabel WHERE {{
        VALUES ?prop {{ {values} }}
        ?prop wikibase:directClaim ?directProp .
        wd:{qid} ?directProp ?value .
        SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }}
    LIMIT 200
    """

    async with httpx.AsyncClient(timeout=20, headers=HTTP_HEADERS) as client:
        resp = await client.get(
            WIKIDATA_SPARQL_URL,
            params={"query": sparql, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        data = resp.json()

    props: list[dict[str, str]] = []
    for binding in data.get("results", {}).get("bindings", []):
        prop_uri = binding.get("prop", {}).get("value", "")
        prop_id = prop_uri.rstrip("/").split("/")[-1]
        raw_value = binding.get("value", {}).get("value", "")
        display_value = binding.get("valueLabel", {}).get("value") or raw_value
        if prop_id in _FORMATTERS and raw_value:
            display_value = _FORMATTERS[prop_id].format(value=raw_value.replace(" ", ""))

        props.append({
            "property_uri": prop_uri,
            "property_name": binding.get("propLabel", {}).get("value", prop_id),
            "value": display_value,
            "source": "wikidata",
        })

    return props


async def apply_grounding_derivatives(entity: Entity, db: Session) -> dict[str, Any]:
    """Set derived URIs and import selected standard triples after grounding."""
    qid = qid_from_wikidata_uri(entity.wikidata_uri)
    if not qid:
        return {"derived_uris": {}, "imported": []}

    derived_uris: dict[str, str] = {}
    try:
        derived_uris = await resolve_wikidata_external_uris(qid)
        if derived_uris.get("worldcat_uri") and not entity.worldcat_uri:
            entity.worldcat_uri = derived_uris["worldcat_uri"]
        if derived_uris.get("dbpedia_uri") and not entity.dbpedia_uri:
            entity.dbpedia_uri = derived_uris["dbpedia_uri"]
    except Exception as exc:
        logger.warning("Failed to resolve Wikidata-derived URIs for %s: %s", qid, exc)

    try:
        image_url = await fetch_wikidata_image_url(qid)
        if image_url:
            entity.image_url = image_url
    except Exception as exc:
        logger.warning("Failed to fetch Wikidata image for %s: %s", qid, exc)

    enabled_ids = get_enabled_standard_property_ids(db)
    imported: list[dict[str, str]] = []
    try:
        properties = await fetch_standard_properties(qid, enabled_ids)
    except Exception as exc:
        logger.warning("Failed to fetch standard triples for %s: %s", qid, exc)
        properties = []

    for prop in properties:
        exists = (
            db.query(EnrichmentProperty)
            .filter(
                EnrichmentProperty.entity_id == entity.id,
                EnrichmentProperty.property_uri == prop["property_uri"],
                EnrichmentProperty.value == prop["value"],
            )
            .first()
        )
        if exists:
            continue
        ep = EnrichmentProperty(
            entity_id=entity.id,
            property_name=prop["property_name"],
            property_uri=prop["property_uri"],
            value=prop["value"],
            source=prop["source"],
        )
        db.add(ep)
        imported.append(prop)

    db.commit()
    return {"derived_uris": derived_uris, "imported": imported}
