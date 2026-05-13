"""WorldCat Entity grounding helpers."""

from __future__ import annotations

import logging
from typing import Any

from app.services.grounding_wikidata import search_wikidata
from app.services.standard_triples import resolve_wikidata_external_uris

logger = logging.getLogger(__name__)


async def search_worldcat(
    query: str,
    entity_type: str | None = None,
    limit: int = 5,
    timeout: int = 15,
    type_filter_enabled: bool = True,
) -> list[dict[str, Any]]:
    """Find WorldCat Entity URIs through Wikidata authority links.

    The old WorldCat OpenSearch endpoint searches bibliographic records, not
    WorldCat Entities, so person/entity searches such as "Gilles Deleuze"
    commonly returned no usable entity result. Wikidata carries the current
    WorldCat Entities identifier (P10832), which is the URI we need here.
    """
    candidates: list[dict[str, Any]] = []
    wd_candidates = await search_wikidata(
        query,
        entity_type,
        limit=max(limit * 2, 5),
        timeout=timeout,
        type_filter_enabled=type_filter_enabled,
    )

    for wd in wd_candidates:
        qid = wd.get("id")
        if not qid:
            continue
        try:
            derived = await resolve_wikidata_external_uris(qid)
        except Exception as exc:
            logger.warning("WorldCat URI lookup via Wikidata failed for %s: %s", qid, exc)
            continue
        worldcat_uri = derived.get("worldcat_uri")
        if not worldcat_uri:
            continue
        candidates.append({
            "source": "worldcat",
            "uri": worldcat_uri,
            "label": wd.get("label", ""),
            "description": wd.get("description", ""),
            "wikidata_uri": wd.get("uri", ""),
        })
        if len(candidates) >= limit:
            break

    return candidates
