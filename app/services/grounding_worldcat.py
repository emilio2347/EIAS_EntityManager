"""Entity grounding against WorldCat."""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree

import httpx

from app.config import WORLDCAT_SRU_URL, HTTP_HEADERS

logger = logging.getLogger(__name__)

# WorldCat OpenSearch namespace
ATOM_NS = "{http://www.w3.org/2005/Atom}"
OS_NS = "{http://a9.com/-/spec/opensearch/1.1/}"


async def search_worldcat(
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search WorldCat for bibliographic records matching the query.

    Uses the WorldCat OpenSearch API.
    Returns a list of candidate dicts with: uri, label, description.
    """
    params = {
        "q": query,
        "count": limit,
        "format": "atom",
    }

    candidates: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=15, headers=HTTP_HEADERS) as client:
            resp = await client.get(WORLDCAT_SRU_URL, params=params)
            resp.raise_for_status()

        root = ElementTree.fromstring(resp.text)

        for entry in root.findall(f"{ATOM_NS}entry"):
            title_el = entry.find(f"{ATOM_NS}title")
            title = title_el.text if title_el is not None and title_el.text else ""

            # Get the WorldCat link
            uri = ""
            for link in entry.findall(f"{ATOM_NS}link"):
                href = link.get("href", "")
                if "worldcat.org" in href:
                    uri = href
                    break

            # Get author/summary
            author_el = entry.find(f"{ATOM_NS}author/{ATOM_NS}name")
            author = author_el.text if author_el is not None and author_el.text else ""

            summary_el = entry.find(f"{ATOM_NS}summary")
            summary = summary_el.text if summary_el is not None and summary_el.text else ""

            description = f"Author: {author}" if author else ""
            if summary:
                description += f" | {summary}" if description else summary

            if title:
                candidates.append({
                    "source": "worldcat",
                    "uri": uri,
                    "label": title,
                    "description": description[:300],
                })

    except Exception as e:
        logger.warning("WorldCat search failed: %s", e)

    return candidates[:limit]
