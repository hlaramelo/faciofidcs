"""Configuration for Facio FIDC monitoring."""

import os
from pathlib import Path

# Project paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "output"

# CVM Open Data Portal
CVM_BASE_URL = "https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS"
CVM_ZIP_PATTERN = "inf_mensal_fidc_{year}{month:02d}.zip"

# Funds to monitor (ordered by PL descending)
FUNDS = [
    {
        "name": "Facio 4 FIDC Financeiros RL",
        "cnpj": "62.627.291/0001-08",
        "cnpj_raw": "62627291000108",
        "status": "Operacional",
        "start_date": "2025-10-01",
    },
    {
        "name": "Facio 3 FIDC RL",
        "cnpj": "60.736.775/0001-51",
        "cnpj_raw": "60736775000151",
        "status": "Operacional",
        "start_date": "2025-06-01",
    },
    {
        "name": "Facio FIDC Financeiros RL",
        "cnpj": "51.119.641/0001-09",
        "cnpj_raw": "51119641000109",
        "status": "Em Liquidacao",
        "start_date": "2023-09-01",
    },
]

# Default date range
DEFAULT_MONTHS_BACK = 12

# Download settings
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds, doubles on each retry

# CSV parsing
CSV_ENCODING = "latin-1"
CSV_SEPARATOR = ";"
