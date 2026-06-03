"""Application configuration and settings."""

import os
from pathlib import Path

# Base directory is the project root (parent of app/)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ONTOLOGY_DIR = DATA_DIR / "ontology"
TEXT_VERSION_DIR = DATA_DIR / "text_versions"
SOURCE_FILE_DIR = DATA_DIR / "source_files"
DB_PATH = DATA_DIR / "eias_entities.db"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
ONTOLOGY_DIR.mkdir(parents=True, exist_ok=True)
TEXT_VERSION_DIR.mkdir(parents=True, exist_ok=True)
SOURCE_FILE_DIR.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://emiliosuarezhode@localhost:5432/eias_database",
)
SQLITE_LEGACY_DB_PATH = Path(os.getenv("SQLITE_LEGACY_DB_PATH", str(DB_PATH)))

# spaCy model
SPACY_MODEL = os.getenv("SPACY_MODEL", "en_core_web_lg")
SPACY_MODEL_VERSION = os.getenv("SPACY_MODEL_VERSION", "3.8.0")

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
