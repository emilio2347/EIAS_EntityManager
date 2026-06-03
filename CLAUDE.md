# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview
Web application for Named Entity Recognition, grounding (Wikidata / DBpedia / WorldCat), coreference resolution, and ontology-backed knowledge management from text documents (txt, md, pdf, json).

## Tech Stack
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.x (SQLite)
- **NER**: spaCy `en_core_web_lg` 3.8.0 (pinned; version enforced at load) + optional coreferee
- **Ontology**: rdflib (.ttl)
- **Frontend**: Vanilla HTML/CSS/JS SPA (no framework, no build step)

## Running
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
uvicorn app.main:app --reload --port 8000          # dev
python launch.py                                    # double-click launcher: picks a free port, opens the browser
```
Then open http://localhost:8000. There is no test suite, lint config, or build step in this repo.

## Architecture

### Request flow
`app/main.py` mounts eight routers under `/api/<name>/` whose names mirror the files in `app/routers/` (documents, entities, ontology, grounding, enrichment, export, profiles, settings). Routers are thin: they validate input, call into `app/services/`, and shape responses. The SPA shell is served from `/` and assets from `/static/`; per-page JS lives in `app/static/js/<router>.js`.

### Data model (`app/models.py`)
- **Document** → many **Mention** → one **Entity**. Mentions store char offsets back into `Document.content_text`.
- **Entity** is the deduplicated canonical record. Grounding writes one or more of `wikidata_uri`, `dbpedia_uri`, `worldcat_uri`, `ontology_class_uri`, `ontology_individual_uri`, `image_url` onto it.
- **EnrichmentProperty** stores key-value triples (with `source`) imported from external KGs after grounding.
- **CoreferenceChain** / **CoreferenceMember** group mention spans within a document and optionally link to an Entity.
- **OntologyMapping** maps a spaCy label (e.g. `PERSON`) to an ontology class URI; used to auto-assign `ontology_class_uri` during NER.
- **ExtractionProfile** holds a JSON list of allowed NER labels; documents reference a profile so NER only persists those types.
- **AppSetting** is a key/value JSON store for runtime pipeline settings.

All primary keys are string UUIDs (`_uuid()` in `models.py`). `alternative_labels` and `allowed_types` are JSON-encoded TEXT — decode/encode explicitly.

### NER pipeline (`app/services/ner.py`)
spaCy is lazy-loaded once into module-global `_nlp`, keyed on `(model_name, coreference_enabled)`. The pipeline rejects loaded models whose `meta.version` doesn't match `SPACY_MODEL_VERSION`. coreferee is optional and wrapped in `try/except` — current `en_core_web_lg` 3.8.0 is **incompatible** with coreferee 1.4 (see `requirements.txt` comment); treat coref as best-effort. Entity dedup uses rapidfuzz with `FUZZY_MATCH_THRESHOLD = 85` (see `app/config.py`).

### Grounding & enrichment
`services/grounding_{wikidata,dbpedia,worldcat}.py` each expose async `search_*` functions returning candidate dicts. The `grounding` router lets the UI pick a candidate, which writes the URI onto the Entity. `services/enrichment.py` then reads those URIs and pulls properties via SPARQL / entity APIs into `EnrichmentProperty`. All external HTTP uses `httpx.AsyncClient` with `HTTP_HEADERS` from config (Wikidata requires a real User-Agent).

### Database lifecycle (`app/database.py`)
On startup (`lifespan` in `main.py`) `create_tables()` runs `Base.metadata.create_all` then `_apply_lightweight_migrations()`, which ALTER-adds any columns listed in `_ADDITIONAL_COLUMNS` that are missing from existing tables. **When adding a new column to an existing model, also add it to `_ADDITIONAL_COLUMNS`** — there is no Alembic; this dict *is* the migration system. Sessions come from the `get_db` FastAPI dependency.

### Data on disk
- `data/eias_entities.db` — SQLite, single file
- `data/ontology/` — persisted .ttl ontology files loaded by `services/ontology_manager.py`

Both are auto-created by `app/config.py` at import time.

## Conventions
- All API endpoints under `/api/` and grouped by router name.
- External KG identifiers live as full URIs on the Entity; helper `qid_from_wikidata_uri` (in `services/standard_triples.py`) extracts QIDs when needed for the Wikidata entity API.
- Static assets are served with `Cache-Control: no-store` on the SPA shell so deploys don't get stuck behind cached HTML.

## AGENTS.md
`AGENTS.md` at the repo root is intended to mirror this file for other coding agents. Keep them in sync when editing.
