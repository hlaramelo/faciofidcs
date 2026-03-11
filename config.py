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

# Funds to monitor (add new Facio FIDCs here)
FUNDS = [
    {
        "name": "Facio FIDC Financeiros RL",
        "cnpj": "51.119.641/0001-09",
        "cnpj_raw": "51119641000109",
    },
    {
        "name": "Facio 2 FIDC",
        "cnpj": "46.955.383/0001-52",
        "cnpj_raw": "46955383000152",
    },
    {
        "name": "Facio 3 FIDC RL",
        "cnpj": "60.736.775/0001-51",
        "cnpj_raw": "60736775000151",
    },
]

# Default date range (last 12 months if not specified)
DEFAULT_MONTHS_BACK = 12

# Download settings
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds, doubles on each retry

# CSV parsing
CSV_ENCODING = "latin-1"
CSV_SEPARATOR = ";"
