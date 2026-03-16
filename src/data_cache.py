"""Persistent data cache for processed FIDC data.

Saves KPIs, per-class data, and raw tables as parquet files so we don't
re-parse all CSVs every time the dashboard loads. Only re-processes when:
  1. User clicks "Atualizar Dados" (force refresh)
  2. New months become available (incremental update)
  3. Cache files don't exist yet (first run)
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd

from config import CACHE_DIR


def _fund_cache_dir(cnpj_raw: str) -> Path:
    """Get cache directory for a specific fund."""
    return CACHE_DIR / cnpj_raw


def _cache_meta_path(cnpj_raw: str) -> Path:
    """Path to cache metadata JSON."""
    return _fund_cache_dir(cnpj_raw) / "meta.json"


def _read_meta(cnpj_raw: str) -> dict:
    """Read cache metadata."""
    path = _cache_meta_path(cnpj_raw)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _write_meta(cnpj_raw: str, meta: dict):
    """Write cache metadata."""
    path = _cache_meta_path(cnpj_raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, default=str))


def is_cache_valid(cnpj_raw: str, start_str: str, end_str: str) -> bool:
    """Check if cache exists and covers the requested date range."""
    meta = _read_meta(cnpj_raw)
    if not meta:
        return False
    return (
        meta.get("start") == start_str
        and meta.get("end") == end_str
        and (_fund_cache_dir(cnpj_raw) / "kpi_df.parquet").exists()
    )


def load_from_cache(cnpj_raw: str) -> tuple:
    """Load cached data. Returns (kpi_df, tables, per_class, cdi_df)."""
    cache_dir = _fund_cache_dir(cnpj_raw)

    # Load KPI DataFrame
    kpi_path = cache_dir / "kpi_df.parquet"
    kpi_df = pd.read_parquet(kpi_path) if kpi_path.exists() else None

    # Load raw tables
    tables = {}
    tables_dir = cache_dir / "tables"
    if tables_dir.exists():
        for pq in sorted(tables_dir.glob("*.parquet")):
            tables[pq.stem] = pd.read_parquet(pq)

    # Load per-class DataFrames
    per_class = {}
    pc_dir = cache_dir / "per_class"
    if pc_dir.exists():
        for pq in sorted(pc_dir.glob("*.parquet")):
            per_class[pq.stem] = pd.read_parquet(pq)

    # Load CDI
    cdi_path = cache_dir / "cdi_df.parquet"
    cdi_df = pd.read_parquet(cdi_path) if cdi_path.exists() else None

    return kpi_df, tables, per_class, cdi_df


def save_to_cache(
    cnpj_raw: str,
    start_str: str,
    end_str: str,
    kpi_df: pd.DataFrame | None,
    tables: dict[str, pd.DataFrame] | None,
    per_class: dict[str, pd.DataFrame] | None,
    cdi_df: pd.DataFrame | None,
):
    """Save processed data to parquet cache."""
    cache_dir = _fund_cache_dir(cnpj_raw)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Save KPI DataFrame
    if kpi_df is not None and not kpi_df.empty:
        kpi_df.to_parquet(cache_dir / "kpi_df.parquet", index=False)

    # Save raw tables
    if tables:
        tables_dir = cache_dir / "tables"
        tables_dir.mkdir(exist_ok=True)
        for name, df in tables.items():
            # Sanitize table name for filename
            safe_name = name.replace("/", "_").replace(" ", "_")
            df.to_parquet(tables_dir / f"{safe_name}.parquet", index=False)

    # Save per-class DataFrames
    if per_class:
        pc_dir = cache_dir / "per_class"
        pc_dir.mkdir(exist_ok=True)
        for name, df in per_class.items():
            df.to_parquet(pc_dir / f"{name}.parquet", index=False)

    # Save CDI
    if cdi_df is not None and not cdi_df.empty:
        cdi_df.to_parquet(cache_dir / "cdi_df.parquet", index=False)

    # Write metadata
    _write_meta(cnpj_raw, {
        "start": start_str,
        "end": end_str,
        "cached_at": date.today().isoformat(),
        "n_months": len(kpi_df) if kpi_df is not None else 0,
    })

    print(f"  Cache saved for {cnpj_raw} ({start_str} to {end_str})")


def clear_cache(cnpj_raw: str | None = None):
    """Clear cache for a specific fund or all funds."""
    import shutil

    if cnpj_raw:
        cache_dir = _fund_cache_dir(cnpj_raw)
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            print(f"  Cache cleared for {cnpj_raw}")
    else:
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            print("  All cache cleared")
