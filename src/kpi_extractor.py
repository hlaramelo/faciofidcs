"""Extracts core financial KPIs from parsed CVM FIDC data."""

import re

import pandas as pd


# Column mapping: CVM column name patterns -> human-readable KPI names
# These patterns match the TAB_* prefixed columns from CVM CSVs.
# The parser auto-discovers columns, so we use flexible matching.
# Note: CVM updated column names in Oct 2024 (CNPJ_FUNDO -> CNPJ_FUNDO_CLASSE)
# and added new columns in Nov 2023 (TAB_I2C5_VL_COTA_FIF, CLASSE, etc.)
COLUMN_PATTERNS = {
    # Table I - Fund summary
    "PL": [
        r"VL_PATRIM_LIQ",
        r"TAB_I2.*PATRIM",
        r"TAB_I2.*PL",
        r"TAB_IV.*PATRIM",
        r"TAB_IV.*VL_PL",
    ],
    "ATIVO_TOTAL": [
        r"VL_ATIVO",
        r"TAB_I1.*ATIVO.*TOTAL",
        r"TAB_I1.*VL_TOTAL",
        r"TAB_I1.*VL_ATIVO",
    ],
    "VALOR_COTA": [
        r"TAB_I2C5_VL_COTA",       # New column added Nov 2023
        r"VL_COTA",
        r"TAB_I2.*VL_COTA",
        r"TAB_X_VL_COTA",
        r"TAB_X.*VL_COTA\b",
    ],
    "NR_COTISTAS": [
        r"NR_COTST",
        r"TAB_X.*NR_COTST",
        r"TAB_X.*QT_COTIST",
        r"TAB_X_1.*NR_COTST",
    ],
    # Credit rights
    "DC_PERFORMAR": [
        r"TAB_II.*PERFORM",
        r"TAB_V.*PERFORM",
        r"TAB_II.*VL_CART.*PERFORM",
    ],
    "DC_NAO_PERFORMAR": [
        r"TAB_II.*NAO.*PERFORM",
        r"TAB_VI.*INADIMP",
        r"TAB_II.*VL_CART.*NAO.*PERFORM",
    ],
    # Acquisitions and redemptions
    "AQUISICOES": [
        r"TAB_VII.*AQUIS",
        r"TAB_I.*AQUIS",
    ],
    "RESGATES": [
        r"RESG",
        r"TAB_X.*RESG",
    ],
    # Monthly return (from tab_X)
    "RENTAB_MES": [
        r"TAB_X_VL_RENTAB_MES",
        r"TAB_X.*RENTAB",
    ],
    # Inadimplência / default (from tab_VI)
    "INADIMPLENCIA_VL": [
        r"TAB_VI.*VL.*INADIMP",
        r"TAB_VI.*VL_CRED.*VENC",
        r"TAB_VI.*ATRASO",
        r"TAB_VI.*VL.*DEFAULT",
    ],
    "INADIMPLENCIA_PROVISAO": [
        r"TAB_VI.*PROVIS",
        r"TAB_VI.*PDD",
        r"TAB_VI.*PERDA",
    ],
    # Substitution of credit rights (from tab_VII)
    "SUBSTITUICAO": [
        r"TAB_VII.*SUBSTIT",
        r"TAB_VII.*VL.*SUBSTIT",
    ],
}


def find_matching_columns(df: pd.DataFrame, patterns: list[str]) -> list[str]:
    """Find columns in DataFrame matching any of the given regex patterns."""
    matched = []
    for col in df.columns:
        for pattern in patterns:
            if re.search(pattern, col, re.IGNORECASE):
                matched.append(col)
                break
    return matched


def extract_kpis(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Extract core financial KPIs from parsed CVM tables.

    Auto-discovers columns based on naming patterns.
    Returns a clean DataFrame with date index and KPI columns.
    """
    # Start with tab_I as the primary data source
    tab_i = tables.get("tab_I", pd.DataFrame())
    if tab_i.empty:
        print("  Warning: Table I not found, KPIs will be limited")
        # Try to find any table with date info
        for name, df in tables.items():
            if "DT_COMPTC" in df.columns:
                tab_i = df
                break

    if tab_i.empty:
        return pd.DataFrame()

    # Build KPI DataFrame
    kpi_data = {"DT_COMPTC": tab_i["DT_COMPTC"]}

    # Add fund identification columns
    for col in ["CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE", "DENOM_SOCIAL", "CLASSE", "CNPJ_CLASSE"]:
        if col in tab_i.columns:
            kpi_data[col] = tab_i[col]

    # Auto-discover KPI columns from all tables
    all_columns_found = {}
    external_merges = []  # DataFrames to merge from non-tab_I tables
    for kpi_name, patterns in COLUMN_PATTERNS.items():
        # Search in tab_I first, then other tables
        for table_name, df in [("tab_I", tab_i)] + [
            (n, d) for n, d in tables.items() if n != "tab_I"
        ]:
            matches = find_matching_columns(df, patterns)
            if matches:
                col = matches[0]
                if kpi_name not in all_columns_found:
                    # Check if values are actually populated (not all NaN)
                    values = pd.to_numeric(df[col], errors="coerce")
                    if values.isna().all():
                        continue  # Skip this table, try next one

                    all_columns_found[kpi_name] = (table_name, col)
                    if table_name == "tab_I":
                        kpi_data[kpi_name] = values
                    else:
                        # Prepare for merge from external table
                        merge_cols = ["DT_COMPTC"]
                        for cnpj_col in ["CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE"]:
                            if cnpj_col in df.columns and cnpj_col in kpi_data:
                                merge_cols.append(cnpj_col)
                                break
                        subset = df[merge_cols + [col]].copy()
                        subset = subset.rename(columns={col: kpi_name})
                        subset[kpi_name] = pd.to_numeric(
                            subset[kpi_name], errors="coerce"
                        )
                        external_merges.append((merge_cols, subset))
                break

    kpi_df = pd.DataFrame(kpi_data)

    # Merge KPIs from external tables
    for merge_cols, subset in external_merges:
        available_merge_cols = [c for c in merge_cols if c in kpi_df.columns]
        if available_merge_cols:
            kpi_df = kpi_df.merge(subset, on=available_merge_cols, how="left")

    # Collect columns already mapped by KPI patterns to avoid duplicates
    mapped_source_cols = {col for _, (_, col) in all_columns_found.items()}

    # Print discovered mappings
    print("\n  KPI column mappings discovered:")
    for kpi_name, (table_name, col) in all_columns_found.items():
        print(f"    {kpi_name} <- {table_name}.{col}")

    return kpi_df


def compute_trends(kpi_df: pd.DataFrame) -> pd.DataFrame:
    """Add month-over-month percentage changes for numeric KPI columns."""
    if kpi_df.empty:
        return kpi_df

    result = kpi_df.copy()
    numeric_cols = result.select_dtypes(include="number").columns

    for col in numeric_cols:
        pct_col = f"{col}_MoM_%"
        result[pct_col] = result[col].pct_change() * 100

    return result


def extract_per_class_data(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Extract per-class time series for PL and Valor da Cota.

    Returns dict with keys like 'pl_por_classe', 'cota_por_classe',
    each containing a DataFrame with DT_COMPTC as index and one column per class.
    """
    result = {}

    # --- PL por Classe ---
    # Try tab_IV first (PL by class), then tab_I with CLASSE column
    pl_class_df = _pivot_by_class(
        tables,
        table_priority=["tab_IV", "tab_I"],
        value_patterns=[r"VL_PATRIM_LIQ", r"TAB_IV.*PATRIM", r"TAB_IV.*VL_PL",
                        r"TAB_I2.*PATRIM", r"VL_PL"],
        label="PL",
    )
    if pl_class_df is not None:
        result["pl_por_classe"] = pl_class_df

    # --- Valor da Cota por Classe ---
    # Try tab_X_2/3/4 (quota details per class type), then tab_I
    cota_class_df = _pivot_by_class(
        tables,
        table_priority=["tab_X_2", "tab_X_3", "tab_X_4", "tab_I"],
        value_patterns=[r"TAB_X_VL_COTA", r"TAB_X.*VL_COTA\b",
                        r"TAB_I2C5_VL_COTA", r"VL_COTA"],
        label="Cota",
    )
    if cota_class_df is not None:
        result["cota_por_classe"] = cota_class_df

    return result


def _pivot_by_class(
    tables: dict[str, pd.DataFrame],
    table_priority: list[str],
    value_patterns: list[str],
    label: str,
) -> pd.DataFrame | None:
    """Pivot a table by class, producing one column per class over time.

    Searches tables in priority order. Looks for a class identifier column
    and a numeric value column matching the patterns.
    """
    # Possible class identifier columns
    class_col_candidates = [
        "CLASSE", "TAB_X_CLASSE_SERIE", "CLASSE_SERIE",
        "TP_CLASSE", "DS_CLASSE",
    ]

    for table_name in table_priority:
        df = tables.get(table_name)
        if df is None or df.empty or "DT_COMPTC" not in df.columns:
            continue

        # Find class column
        class_col = None
        for cc in class_col_candidates:
            if cc in df.columns:
                unique_vals = df[cc].dropna().unique()
                if len(unique_vals) > 1:
                    class_col = cc
                    break

        if class_col is None:
            # For tab_X_2/3/4, use the table name itself as class identifier
            if table_name.startswith("tab_X_"):
                class_map = {
                    "tab_X_2": "Senior",
                    "tab_X_3": "Mezanino",
                    "tab_X_4": "Subordinada",
                }
                if table_name in class_map:
                    return _build_from_separate_tables(
                        tables, class_map, value_patterns, label
                    )
            continue

        # Find value column
        value_col = None
        for col in df.columns:
            for pattern in value_patterns:
                if re.search(pattern, col, re.IGNORECASE):
                    values = pd.to_numeric(df[col], errors="coerce")
                    if not values.isna().all():
                        value_col = col
                        break
            if value_col:
                break

        if value_col is None:
            continue

        # Pivot: rows=date, columns=class, values=numeric value
        pivot_df = df[["DT_COMPTC", class_col, value_col]].copy()
        pivot_df[value_col] = pd.to_numeric(pivot_df[value_col], errors="coerce")
        pivot_df = pivot_df.dropna(subset=[value_col])

        if pivot_df.empty:
            continue

        pivoted = pivot_df.pivot_table(
            index="DT_COMPTC",
            columns=class_col,
            values=value_col,
            aggfunc="first",
        )

        if pivoted.empty or pivoted.columns.empty:
            continue

        # Clean column names
        pivoted.columns = [f"{label} - {str(c).strip()}" for c in pivoted.columns]
        pivoted = pivoted.reset_index().sort_values("DT_COMPTC")

        print(f"  Per-class {label}: {len(pivoted)} months, classes: {list(pivoted.columns[1:])}")
        return pivoted

    return None


def _build_from_separate_tables(
    tables: dict[str, pd.DataFrame],
    class_map: dict[str, str],
    value_patterns: list[str],
    label: str,
) -> pd.DataFrame | None:
    """Build per-class DataFrame from separate tab_X_2/3/4 tables."""
    frames = []

    for table_name, class_name in class_map.items():
        df = tables.get(table_name)
        if df is None or df.empty or "DT_COMPTC" not in df.columns:
            continue

        # Find value column
        for col in df.columns:
            for pattern in value_patterns:
                if re.search(pattern, col, re.IGNORECASE):
                    values = pd.to_numeric(df[col], errors="coerce")
                    if not values.isna().all():
                        series_df = df[["DT_COMPTC"]].copy()
                        series_df[f"{label} - {class_name}"] = values
                        # Aggregate by date (in case of duplicates)
                        series_df = series_df.groupby("DT_COMPTC").first().reset_index()
                        frames.append(series_df)
                        break
            if frames and frames[-1].columns[-1].endswith(class_name):
                break

    if not frames:
        return None

    # Merge all class series on date
    result = frames[0]
    for f in frames[1:]:
        result = result.merge(f, on="DT_COMPTC", how="outer")

    result = result.sort_values("DT_COMPTC").reset_index(drop=True)
    print(f"  Per-class {label}: {len(result)} months, classes: {list(result.columns[1:])}")
    return result


def get_latest_summary(kpi_df: pd.DataFrame) -> dict:
    """Get the latest month's KPI values as a summary dict."""
    if kpi_df.empty:
        return {}

    latest = kpi_df.iloc[-1]
    summary = {}

    if "DT_COMPTC" in kpi_df.columns:
        summary["Data Referencia"] = latest["DT_COMPTC"]

    for col in kpi_df.select_dtypes(include="number").columns:
        if not col.endswith("_MoM_%"):
            summary[col] = latest[col]

    return summary
