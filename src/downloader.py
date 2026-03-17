"""Downloads FIDC monthly report ZIPs from CVM Open Data Portal."""

import time
import zipfile
from datetime import date
from pathlib import Path

import requests

from config import (
    CVM_BASE_URL,
    CVM_ZIP_PATTERN,
    CSV_ENCODING,
    DATA_DIR,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
)


def get_monthly_periods(start_date: date, end_date: date) -> list[tuple[int, int]]:
    """Return list of (year, month) tuples between start and end dates."""
    periods = []
    current = start_date.replace(day=1)
    end = end_date.replace(day=1)
    while current <= end:
        periods.append((current.year, current.month))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return periods


def download_file(url: str, dest: Path) -> bool:
    """Download a file with retry logic. Returns True if successful."""
    delay = RETRY_DELAY
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)
                return True
            elif resp.status_code == 404:
                # File doesn't exist yet (month not published)
                return False
            else:
                print(f"  HTTP {resp.status_code} for {url}")
        except requests.RequestException as e:
            print(f"  Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
        if attempt < MAX_RETRIES - 1:
            time.sleep(delay)
            delay *= 2
    return False


def extract_zip(zip_path: Path, output_dir: Path) -> list[Path]:
    """Extract CSV files from a ZIP. Returns list of extracted file paths."""
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith(".csv"):
                zf.extract(name, output_dir)
                extracted.append(output_dir / name)
    return extracted


def download_monthly_zips(
    start_date: date,
    end_date: date,
    cache_dir: Path | None = None,
) -> dict[tuple[int, int], list[Path]]:
    """Download and extract monthly FIDC report ZIPs from CVM.

    Returns dict mapping (year, month) to list of extracted CSV paths.
    Skips already-downloaded files.
    """
    cache_dir = cache_dir or DATA_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    periods = get_monthly_periods(start_date, end_date)
    results = {}

    for year, month in periods:
        zip_name = CVM_ZIP_PATTERN.format(year=year, month=month)
        zip_path = cache_dir / zip_name
        extract_dir = cache_dir / f"{year}{month:02d}"

        # Check if already extracted
        if extract_dir.exists() and any(extract_dir.glob("*.csv")):
            csv_files = list(extract_dir.glob("*.csv"))
            results[(year, month)] = csv_files
            print(f"  [{year}-{month:02d}] Using cached data ({len(csv_files)} files)")
            continue

        # Download
        url = f"{CVM_BASE_URL}/{zip_name}"
        print(f"  [{year}-{month:02d}] Downloading from CVM...")
        if download_file(url, zip_path):
            extract_dir.mkdir(parents=True, exist_ok=True)
            csv_files = extract_zip(zip_path, extract_dir)
            results[(year, month)] = csv_files
            print(f"  [{year}-{month:02d}] Extracted {len(csv_files)} CSV files")
            # Clean up ZIP to save space
            zip_path.unlink(missing_ok=True)
        else:
            print(f"  [{year}-{month:02d}] Not available (may not be published yet)")

    return results
