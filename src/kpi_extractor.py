"""Extracts core financial KPIs from parsed CVM FIDC data."""

import re

import pandas as pd


# Column mapping: CVM column name patterns -> human-readable KPI names
# These patterns match the TAB_* prefixed columns from CVM CSVs.
# The parser auto-discovers columns, so we use flexible matching.
COLUMN_PATTERNS = {
    # Table I - Fund summary
    "PL": [
        r"VL_PATRIM_LIQ",
        r"TAB_I2.*PATRIM",
        r"TAB_I2.*PL",
        r"TAB_IV.*PATRIM",
    ],
    "ATIVO_TOTAL": [
        r"VL_ATIVO",
        r"TAB_I1.*ATIVO.*TOTAL",
        r"TAB_I1.*VL_TOTAL",
    ],
    "VALOR_COTA": [
        r"VL_COTA",
        r"TAB_I2.*VL_COTA",
        r"TAB_X.*VL_COTA",
    ],
    "NR_COTISTAS": [
        r"NR_COTST",
        r"TAB_X.*NR_COTST",
        r"TAB_X.*QT_COTIST",
    ],
    # Credit rights
    "DC_PERFORMAR": [
        r"TAB_II.*PERFORM",
        r"TAB_V.*PERFORM",
    ],
    "DC_NAO_PERFORMAR": [
        r"TAB_II.*NAO.*PERFORM",
        r"TAB_VI.*INADIMP",
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
    for col in ["CNPJ_FUNDO", "DENOM_SOCIAL", "CLASSE", "CNPJ_CLASSE"]:
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
                    all_columns_found[kpi_name] = (table_name, col)
                    if table_name == "tab_I":
                        kpi_data[kpi_name] = pd.to_numeric(
                            tab_i[col], errors="coerce"
                        )
                    else:
                        # Prepare for merge from external table
                        merge_cols = ["DT_COMPTC"]
                        if "CNPJ_FUNDO" in df.columns:
                            merge_cols.append("CNPJ_FUNDO")
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
