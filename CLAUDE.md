# EIAS Entity Manager

## Overview
Web application for Named Entity Recognition, grounding, coreference resolution, and knowledge management from text documents.

## Tech Stack
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy (SQLite)
- **NER**: spaCy (en_core_web_lg) + coreferee
- **Ontology**: rdflib (.ttl parsing)
- **Frontend**: Vanilla HTML/CSS/JS (no framework)

## Project Structure
- `app/main.py` — FastAPI entry point
- `app/models.py` — SQLAlchemy ORM models
- `app/routers/` — API route handlers
- `app/services/` — Business logic (NER, grounding, export, etc.)
- `app/static/` — Frontend SPA
- `data/` — SQLite DB + persisted ontology files

## Running
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
python -m coreferee install en
uvicorn app.main:app --reload --port 8000
```
Then open http://localhost:8000

## Key Conventions
- All API endpoints under `/api/`
- Entity IDs are UUIDs (string)
- Ontology file persisted in `data/ontology/`
- SQLite database at `data/eias_entities.db`
- Entity deduplication uses rapidfuzz (threshold: 85)
