"""Application configuration and settings."""

import os
from pathlib import Path

# Base directory is the project root (parent of app/)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ONTOLOGY_DIR = DATA_DIR / "ontology"
DB_PATH = DATA_DIR / "eias_entities.db"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
ONTOLOGY_DIR.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_URL = f"sqlite:///{DB_PATH}"

# spaCy model
SPACY_MODEL = os.getenv("SPACY_MODEL", "en_core_web_lg")

# External API endpoints
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
DBPEDIA_SPOTLIGHT_URL = "https://api.dbpedia-spotlight.org/en/annotate"
DBPEDIA_LOOKUP_URL = "https://lookup.dbpedia.org/api/search"
DBPEDIA_SPARQL_URL = "https://dbpedia.org/sparql"
WORLDCAT_SRU_URL = "https://www.worldcat.org/webservices/catalog/search/worldcat/opensearch"

# NER settings
FUZZY_MATCH_THRESHOLD = 85  # rapidfuzz score threshold for entity dedup

# Upload limits
MAX_UPLOAD_SIZE_MB = 50

# HTTP client headers (Wikidata requires a proper User-Agent)
HTTP_HEADERS = {
    "User-Agent": "EIAS-EntityManager/0.1 (https://github.com/eias; emilio@example.com)",
}
