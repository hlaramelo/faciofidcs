"""Parses CVM FIDC monthly report CSVs and filters by fund CNPJ."""

from pathlib import Path

import pandas as pd

from config import CSV_ENCODING, CSV_SEPARATOR


def read_csv_file(csv_path: Path) -> pd.DataFrame:
    """Read a single CVM CSV file with proper encoding and separator."""
    return pd.read_csv(
        csv_path,
        sep=CSV_SEPARATOR,
        encoding=CSV_ENCODING,
        low_memory=False,
    )


def filter_by_cnpj(df: pd.DataFrame, cnpjs: list[str]) -> pd.DataFrame:
    """Filter DataFrame to only include rows for the specified CNPJs.

    Handles both formatted (XX.XXX.XXX/XXXX-XX) and raw (XXXXXXXXXXXXXX) CNPJs.
    """
    if df.empty:
        return df

    cnpj_col = None
    for col in ["CNPJ_FUNDO", "CNPJ_CLASSE"]:
        if col in df.columns:
            cnpj_col = col
            break

    if cnpj_col is None:
        return df

    # Normalize CNPJs by removing formatting characters
    raw_cnpjs = {c.replace(".", "").replace("/", "").replace("-", "") for c in cnpjs}
    df_cnpj_raw = df[cnpj_col].astype(str).str.replace(r"[./-]", "", regex=True)
    return df[df_cnpj_raw.isin(raw_cnpjs)].copy()


def find_csv_files(
    data_dirs: dict[tuple[int, int], list[Path]], pattern: str
) -> list[Path]:
    """Find CSV files matching a pattern across all period directories."""
    files = []
    for period, csv_paths in sorted(data_dirs.items()):
        for p in csv_paths:
            if pattern.lower() in p.name.lower():
                files.append(p)
    return files


def parse_table(
    csv_files: list[Path], cnpjs: list[str]
) -> pd.DataFrame:
    """Parse and concatenate CSV files for a specific table, filtered by CNPJ."""
    frames = []
    for csv_path in csv_files:
        try:
            df = read_csv_file(csv_path)
            df = filter_by_cnpj(df, cnpjs)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            print(f"  Warning: Could not parse {csv_path.name}: {e}")

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)

    # Parse date column
    if "DT_COMPTC" in result.columns:
        result["DT_COMPTC"] = pd.to_datetime(result["DT_COMPTC"], errors="coerce")
        result = result.sort_values("DT_COMPTC").reset_index(drop=True)

    # Drop exact duplicates (same fund, same date)
    id_cols = [c for c in ["CNPJ_FUNDO", "DT_COMPTC", "CLASSE"] if c in result.columns]
    if id_cols:
        result = result.drop_duplicates(subset=id_cols, keep="last")

    return result


def parse_all_tables(
    data_dirs: dict[tuple[int, int], list[Path]],
    cnpjs: list[str],
) -> dict[str, pd.DataFrame]:
    """Parse all available tables from downloaded CVM data.

    Returns dict mapping table name to filtered DataFrame.
    Key tables:
      - tab_I: Fund summary (assets, liabilities, PL, quota values)
      - tab_II: Credit rights classification
      - tab_III: Liabilities detail
      - tab_IV: PL detail by class
      - tab_V through tab_VII: Credit rights by maturity/status
      - tab_X_1 through tab_X_7: Quotaholders, returns, transactions
    """
    # Table patterns to look for in filenames
    table_patterns = [
        "tab_I_",     # Table I - fund summary (NOT tab_II, tab_IV, etc.)
        "tab_II_",    # Table II - credit rights classification
        "tab_III_",   # Table III - liabilities
        "tab_IV_",    # Table IV - PL by class
        "tab_V_",     # Table V - credit rights by maturity
        "tab_VI_",    # Table VI - credit rights by default status
        "tab_VII_",   # Table VII - credit rights acquisitions
        "tab_X_1",    # Table X.1 - quotaholders
        "tab_X_2",    # Table X.2 - quota details (senior)
        "tab_X_3",    # Table X.3 - quota details (mezanino)
        "tab_X_4",    # Table X.4 - quota details (subordinada)
    ]

    tables = {}
    for pattern in table_patterns:
        csv_files = find_csv_files(data_dirs, pattern)
        if csv_files:
            table_name = pattern.rstrip("_")
            df = parse_table(csv_files, cnpjs)
            if not df.empty:
                tables[table_name] = df
                print(f"  Parsed {table_name}: {len(df)} rows, {len(df.columns)} columns")

    return tables


def discover_columns(tables: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    """Discover and return available columns per table for debugging."""
    return {name: df.columns.tolist() for name, df in tables.items()}
