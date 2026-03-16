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


def filter_by_cnpj(
    df: pd.DataFrame, cnpjs: list[str], fund_names: list[str] | None = None
) -> pd.DataFrame:
    """Filter DataFrame to only include rows for the specified CNPJs.

    Handles both formatted (XX.XXX.XXX/XXXX-XX) and raw (XXXXXXXXXXXXXX) CNPJs.
    When the table uses CNPJ_FUNDO_CLASSE (class-level CNPJs), finds the matching
    class first, then includes all sibling classes of the same fund.
    fund_names: optional list of fund base names for DENOM_SOCIAL fallback matching.
    """
    if df.empty:
        return df

    # Normalize input CNPJs
    raw_cnpjs = {c.replace(".", "").replace("/", "").replace("-", "") for c in cnpjs}

    # If CNPJ_FUNDO exists, filter on it (matches all classes of the fund)
    if "CNPJ_FUNDO" in df.columns:
        df_cnpj_raw = df["CNPJ_FUNDO"].astype(str).str.replace(r"[./-]", "", regex=True)
        result = df[df_cnpj_raw.isin(raw_cnpjs)].copy()
        if not result.empty:
            return result

    # Try CNPJ_FUNDO_CLASSE — but expand to all sibling classes
    if "CNPJ_FUNDO_CLASSE" in df.columns:
        df_cnpj_raw = df["CNPJ_FUNDO_CLASSE"].astype(str).str.replace(r"[./-]", "", regex=True)
        direct_match = df[df_cnpj_raw.isin(raw_cnpjs)]

        if not direct_match.empty:
            # Find sibling classes via DENOM_SOCIAL (fund name) or shared date rows
            if "DENOM_SOCIAL" in df.columns:
                fund_names_from_match = direct_match["DENOM_SOCIAL"].dropna().unique()
                # Extract base fund name (strip class suffixes)
                base_names = set()
                for name in fund_names_from_match:
                    base = _extract_fund_base_name(str(name))
                    base_names.add(base)
                # Find all rows whose DENOM_SOCIAL starts with any base name
                if base_names:
                    mask = df["DENOM_SOCIAL"].apply(
                        lambda x: any(
                            _extract_fund_base_name(str(x)) == b for b in base_names
                        )
                        if pd.notna(x) else False
                    )
                    result = df[mask].copy()
                    if not result.empty:
                        return result

            return direct_match.copy()

    # Fallback: try CNPJ_CLASSE
    if "CNPJ_CLASSE" in df.columns:
        df_cnpj_raw = df["CNPJ_CLASSE"].astype(str).str.replace(r"[./-]", "", regex=True)
        result = df[df_cnpj_raw.isin(raw_cnpjs)].copy()
        if not result.empty:
            return result

    # Fallback: search by fund name in DENOM_SOCIAL when no CNPJ match
    if fund_names and "DENOM_SOCIAL" in df.columns:
        base_names = {_extract_fund_base_name(n) for n in fund_names}
        mask = df["DENOM_SOCIAL"].apply(
            lambda x: any(
                _extract_fund_base_name(str(x)) == b for b in base_names
            )
            if pd.notna(x) else False
        )
        result = df[mask].copy()
        if not result.empty:
            return result

    return pd.DataFrame(columns=df.columns)


def _extract_fund_base_name(name: str) -> str:
    """Extract base fund name, stripping class/series suffixes.

    E.g. 'Facio 3 FIDC RL - Subclasse Senior Serie 1' -> 'Facio 3 FIDC RL'
    """
    # Split on common separators between fund name and class info
    for sep in [" - Subclasse", " - Classe", " - Sub", " Subclasse", " Classe Senior",
                " Classe Mezanino", " Classe Subordinada", " Classe Mezzanin",
                " Senior", " Mezanino", " Subordinada", " - Senior", " - Mezanino",
                " - Subordinada", " | Sub", " | Classe"]:
        idx = name.upper().find(sep.upper())
        if idx > 0:
            return name[:idx].strip()
    return name.strip()


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
    csv_files: list[Path], cnpjs: list[str], fund_names: list[str] | None = None
) -> pd.DataFrame:
    """Parse and concatenate CSV files for a specific table, filtered by CNPJ."""
    frames = []
    for csv_path in csv_files:
        try:
            df = read_csv_file(csv_path)
            df = filter_by_cnpj(df, cnpjs, fund_names=fund_names)
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

    # Drop exact duplicates (same fund, same date, same class)
    id_cols = [c for c in ["CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE", "DT_COMPTC", "CLASSE", "DENOM_SOCIAL"] if c in result.columns]
    if id_cols:
        result = result.drop_duplicates(subset=id_cols, keep="last")

    return result


def parse_all_tables(
    data_dirs: dict[tuple[int, int], list[Path]],
    cnpjs: list[str],
    fund_names: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Parse all available tables from downloaded CVM data.

    Returns dict mapping table name to filtered DataFrame.
    fund_names: optional list of fund names for DENOM_SOCIAL fallback filtering.
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
        "tab_X_5",    # Table X.5 - quota returns/rentabilidade
        "tab_X_6",    # Table X.6 - additional quota info
        "tab_X_7",    # Table X.7 - additional quota info
    ]

    # Parse tab_I first to discover fund names for DENOM_SOCIAL fallback
    discovered_fund_names = list(fund_names) if fund_names else []

    tables = {}
    # Parse tab_I first to extract fund names
    tab_i_files = find_csv_files(data_dirs, "tab_I_")
    if tab_i_files:
        tab_i_df = parse_table(tab_i_files, cnpjs, fund_names=discovered_fund_names or None)
        if not tab_i_df.empty:
            tables["tab_I"] = tab_i_df
            print(f"  Parsed tab_I: {len(tab_i_df)} rows, {len(tab_i_df.columns)} columns")
            # Extract fund base names for fallback filtering in other tables
            if "DENOM_SOCIAL" in tab_i_df.columns:
                for name in tab_i_df["DENOM_SOCIAL"].dropna().unique():
                    base = _extract_fund_base_name(str(name))
                    if base and base not in discovered_fund_names:
                        discovered_fund_names.append(base)
                print(f"  Discovered fund names for filtering: {discovered_fund_names}")

    # Parse remaining tables using discovered fund names as fallback
    for pattern in table_patterns:
        if pattern == "tab_I_":
            continue  # Already parsed
        csv_files = find_csv_files(data_dirs, pattern)
        if csv_files:
            table_name = pattern.rstrip("_")
            df = parse_table(csv_files, cnpjs, fund_names=discovered_fund_names or None)
            if not df.empty:
                tables[table_name] = df
                print(f"  Parsed {table_name}: {len(df)} rows, {len(df.columns)} columns")

    return tables


def discover_columns(tables: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    """Discover and return available columns per table for debugging."""
    return {name: df.columns.tolist() for name, df in tables.items()}
