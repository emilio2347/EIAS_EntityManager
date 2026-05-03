"""Coreference resolution using coreferee."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import CoreferenceChain, CoreferenceMember, Entity, Mention
from app.services.ner import get_nlp

logger = logging.getLogger(__name__)


def resolve_coreferences(
    text: str,
    document_id: str,
    db: Session,
) -> list[dict[str, Any]]:
    """Run coreference resolution and link chains to entities.

    Should be called after NER has already been run on the same document.
    Returns a list of chain dicts.
    """
    nlp = get_nlp()
    doc = nlp(text)

    # Check if coreferee is available
    if not hasattr(doc, "_") or not hasattr(doc._, "coref_chains"):
        logger.warning("coreferee not available on this doc — skipping coreference")
        return []

    coref_chains = doc._.coref_chains
    if coref_chains is None:
        return []

    results: list[dict[str, Any]] = []

    for chain_idx, chain in enumerate(coref_chains):
        members_data: list[dict[str, Any]] = []

        # Build member spans
        for mention in chain:
            # coreferee mentions are lists of token indices
            token_indices = list(mention)
            if not token_indices:
                continue
            start_token = doc[token_indices[0]]
            end_token = doc[token_indices[-1]]
            surface = doc[token_indices[0]: token_indices[-1] + 1].text

            members_data.append({
                "surface_form": surface,
                "start_char": start_token.idx,
                "end_char": end_token.idx + len(end_token.text),
            })

        if not members_data:
            continue

        # Try to link the chain to an existing entity by checking if any
        # member overlaps with a known mention in this document
        entity_id = _match_chain_to_entity(members_data, document_id, db)

        chain_record = CoreferenceChain(
            document_id=document_id,
            entity_id=entity_id,
            chain_index=chain_idx,
        )
        db.add(chain_record)
        db.flush()

        for md in members_data:
            member = CoreferenceMember(
                chain_id=chain_record.id,
                surface_form=md["surface_form"],
                start_char=md["start_char"],
                end_char=md["end_char"],
            )
            db.add(member)

        results.append({
            "chain_id": chain_record.id,
            "chain_index": chain_idx,
            "entity_id": entity_id,
            "members": members_data,
        })

    db.commit()
    return results


def _match_chain_to_entity(
    members: list[dict[str, Any]],
    document_id: str,
    db: Session,
) -> str | None:
    """Check if any chain member overlaps with an existing entity mention."""
    for md in members:
        # Look for a mention in this document that overlaps in character range
        mention = (
            db.query(Mention)
            .filter(
                Mention.document_id == document_id,
                Mention.start_char <= md["start_char"],
                Mention.end_char >= md["end_char"],
            )
            .first()
        )
        if mention:
            return mention.entity_id

        # Also try exact overlap
        mention = (
            db.query(Mention)
            .filter(
                Mention.document_id == document_id,
                Mention.start_char == md["start_char"],
                Mention.end_char == md["end_char"],
            )
            .first()
        )
        if mention:
            return mention.entity_id

    return None
