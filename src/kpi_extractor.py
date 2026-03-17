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
        r"TAB_X_VL_COTA\b",         # tab_X_2 cota value (most reliable)
        r"TAB_I2C5_VL_COTA\b",      # New column added Nov 2023 (exact match)
        # Note: do NOT match TAB_I2C5_VL_COTA_FUNDO_ICVM555 or TAB_I2C5_VL_COTA_FIF
        # — those are the value of fund shares held as assets, not the fund's own cota
        r"VL_COTA\b",
    ],
    "NR_COTISTAS": [
        # Handled specially in extract_kpis — sum all NR_COTST breakdown columns
        # These patterns are fallbacks if the special handling doesn't find data
        r"NR_COTST_TOTAL",
        r"NR_COTISTAS_TOTAL",
        r"QT_COTST_TOTAL",
    ],
    # Credit rights — performing (tab_II, tab_V, or tab_I)
    "DC_PERFORMAR": [
        r"TAB_II.*PERFORM",
        r"TAB_V.*PERFORM",
        r"TAB_II.*VL_CART.*PERFORM",
        r"VL_CART.*PERFORM",
        r"DC_PERFORMAR",
        r"VL_DIREITOS.*PERFORM",
        # Resolution 175 / newer layouts
        r"TAB_I1.*DIR.*CRED(?!.*NAO)",   # tab_I1 direitos creditorios (not NAO)
        r"TAB_I1.*CARTEIRA(?!.*NAO)",     # tab_I1 carteira (not NAO)
        r"VL_TOTAL.*PERFORM",
        r"VL_DC.*PERFORM",
    ],
    # Credit rights — non-performing (tab_II, tab_VI)
    "DC_NAO_PERFORMAR": [
        r"TAB_II.*NAO.*PERFORM",
        r"TAB_VI.*INADIMP",
        r"TAB_II.*VL_CART.*NAO.*PERFORM",
        r"VL_CART.*NAO.*PERFORM",
        r"DC_NAO_PERFORMAR",
        r"VL_DIREITOS.*NAO.*PERFORM",
        # Resolution 175 / newer layouts
        r"TAB_VI.*VL.*TOTAL(?!.*PERFORM)",  # tab_VI total (default portfolio)
        r"VL_TOTAL.*NAO.*PERFORM",
        r"VL_DC.*NAO.*PERFORM",
    ],
    # Acquisitions and redemptions
    "AQUISICOES": [
        r"TAB_VII.*AQUIS",
        r"TAB_I.*AQUIS",
        r"VL_AQUIS",
        # Resolution 175 / newer layouts
        r"TAB_VII.*CESS[AÃ]O",             # cessão (assignment)
        r"TAB_VII.*VL.*TOTAL",              # tab_VII total
        r"VL_CESS[AÃ]O",
        r"VL_DC_AQUIS",
    ],
    "RESGATES": [
        r"RESG",
        r"TAB_X.*RESG",
        r"VL_RESG",
        # Resolution 175 / newer layouts
        r"TAB_X.*AMORTIZ",                  # amortizações
        r"VL_AMORTIZ",
    ],
    # Monthly return (from tab_X)
    "RENTAB_MES": [
        r"TAB_X_VL_RENTAB_MES",
        r"TAB_X.*RENTAB",
        r"RENTAB_MES",
        r"VL_RENTAB",
    ],
    # Inadimplência / default (from tab_VI)
    "INADIMPLENCIA_VL": [
        r"TAB_VI.*VL.*INADIMP",
        r"TAB_VI.*VL_CRED.*VENC",
        r"TAB_VI.*ATRASO",
        r"TAB_VI.*VL.*DEFAULT",
        r"VL_INADIMP",
        r"VL_CRED.*VENC",
        # Resolution 175 / newer layouts
        r"TAB_VI.*VL.*TOTAL",
        r"TAB_V.*VENC",                     # tab_V vencidos
    ],
    "INADIMPLENCIA_PROVISAO": [
        r"TAB_VI.*PROVIS",
        r"TAB_VI.*PDD",
        r"TAB_VI.*PERDA",
        r"VL_PROVIS",
        r"VL_PDD",
        # Resolution 175 / newer layouts
        r"TAB_I.*PROVIS",
        r"TAB_I.*PDD",
    ],
    # Substitution of credit rights (from tab_VII)
    "SUBSTITUICAO": [
        r"TAB_VII.*SUBSTIT",
        r"TAB_VII.*VL.*SUBSTIT",
        r"VL_SUBSTIT",
    ],
    # Overdue (vencidos) credit rights — past-due receivables (from tab_VI)
    "VENCIDOS_VL": [
        r"TAB_VI.*VL.*VENC",
        r"TAB_VI.*VENCID",
        r"TAB_VI.*CR[EÉ]D.*VENC",
        r"VL_CRED.*VENC",
        r"VL_VENCID",
        r"TAB_V.*VL.*VENC",
    ],
    # Buyback / repurchase of credit rights (from tab_VII)
    "RECOMPRA_VL": [
        r"TAB_VII.*RECOMPRA",
        r"TAB_VII.*VL.*RECOMPRA",
        r"VL_RECOMPRA",
        r"RECOMPRA",
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

    # Check if tab_I has multiple rows per date (one per class)
    has_classes = False
    class_col_for_info = None
    for cc in ["CLASSE", "DENOM_SOCIAL"]:
        if cc in tab_i.columns:
            unique_per_date = tab_i.groupby("DT_COMPTC")[cc].nunique()
            if (unique_per_date > 1).any():
                has_classes = True
                class_col_for_info = cc
                break

    # Build KPI DataFrame
    kpi_data = {"DT_COMPTC": tab_i["DT_COMPTC"]}

    # Add fund identification columns (ensure CNPJ columns stay as strings)
    for col in ["CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE", "DENOM_SOCIAL", "CLASSE", "CNPJ_CLASSE"]:
        if col in tab_i.columns:
            kpi_data[col] = tab_i[col].astype(str) if "CNPJ" in col else tab_i[col]

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

    # If tab_I has multiple rows per date (per class), aggregate to fund level
    # for the KPI summary (per-class data is handled by extract_per_class_data)
    if has_classes and "DT_COMPTC" in kpi_df.columns:
        print(f"  Multi-class data detected via '{class_col_for_info}', aggregating to fund level...")
        numeric_cols = kpi_df.select_dtypes(include="number").columns.tolist()
        # For PL and totals, sum across classes; for rates/cota, take mean
        sum_cols = [c for c in numeric_cols if c in (
            "PL", "ATIVO_TOTAL", "DC_PERFORMAR", "DC_NAO_PERFORMAR",
            "AQUISICOES", "RESGATES", "INADIMPLENCIA_VL", "INADIMPLENCIA_PROVISAO",
            "SUBSTITUICAO", "VENCIDOS_VL", "RECOMPRA_VL",
        )]
        # NR_COTISTAS: use max, not sum — each class row reports the same
        # fund-level total or a class-level count that shouldn't be summed
        # (cotistas may hold multiple classes, summing double-counts)
        max_cols = [c for c in numeric_cols if c in ("NR_COTISTAS",)]
        mean_cols = [c for c in numeric_cols if c in (
            "VALOR_COTA", "RENTAB_MES",
        )]

        agg_dict = {}
        for c in sum_cols:
            agg_dict[c] = "sum"
        for c in max_cols:
            agg_dict[c] = "max"
        for c in mean_cols:
            agg_dict[c] = "mean"
        # Any remaining numeric columns default to first
        for c in numeric_cols:
            if c not in agg_dict:
                agg_dict[c] = "first"

        if agg_dict:
            kpi_df = kpi_df.groupby("DT_COMPTC", as_index=False).agg(agg_dict)

    # Special handling: compute NR_COTISTAS by summing all cotistas breakdown columns
    # from tab_X_1 if not already found or if only a partial column was matched
    if "NR_COTISTAS" not in kpi_df.columns or kpi_df["NR_COTISTAS"].isna().all():
        tab_x1 = tables.get("tab_X_1")
        if tab_x1 is not None and "DT_COMPTC" in tab_x1.columns:
            cotst_cols = [c for c in tab_x1.columns if re.search(r"NR_COTST", c, re.IGNORECASE)]
            if cotst_cols:
                # Sum NR_COTST breakdown columns (PF, PJ, etc.) within each row,
                # then take the MAX across class rows per date to avoid double-counting
                tab_x1_numeric = tab_x1[["DT_COMPTC"]].copy()
                for c in cotst_cols:
                    tab_x1_numeric[c] = pd.to_numeric(tab_x1[c], errors="coerce")
                # Sum breakdown columns per row (PF + PJ + ...), then max per date
                tab_x1_numeric["_nr_total_row"] = tab_x1_numeric[cotst_cols].sum(axis=1)
                nr_total = tab_x1_numeric.groupby("DT_COMPTC")["_nr_total_row"].max().reset_index()
                nr_total.columns = ["DT_COMPTC", "NR_COTISTAS"]
                # Merge into kpi_df
                if "NR_COTISTAS" in kpi_df.columns:
                    kpi_df = kpi_df.drop(columns=["NR_COTISTAS"])
                kpi_df = kpi_df.merge(nr_total, on="DT_COMPTC", how="left")
                all_columns_found["NR_COTISTAS"] = ("tab_X_1", f"SUM({len(cotst_cols)} cols)")
                print(f"  NR_COTISTAS: computed by summing {len(cotst_cols)} breakdown columns from tab_X_1")

    # Print discovered mappings
    print("\n  KPI column mappings discovered:")
    for kpi_name, (table_name, col) in all_columns_found.items():
        print(f"    {kpi_name} <- {table_name}.{col}")

    # Log missing KPIs with available columns for diagnosis
    missing = [k for k in COLUMN_PATTERNS if k not in all_columns_found]
    if missing:
        print(f"\n  KPIs NOT found: {', '.join(missing)}")
        print("  Available columns per table (for diagnosis):")
        for tname, tdf in tables.items():
            # Only show numeric-ish columns (skip date/CNPJ/text)
            numeric_cols = [c for c in tdf.columns
                           if c not in ("DT_COMPTC", "CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE",
                                        "CNPJ_CLASSE", "DENOM_SOCIAL", "CLASSE",
                                        "CLASSE_UNICA", "TP_CLASSE", "NM_CLASSE")]
            print(f"    {tname} ({len(tdf)} rows): {numeric_cols}")

    return kpi_df


def compute_trends(kpi_df: pd.DataFrame) -> pd.DataFrame:
    """Add month-over-month percentage changes and computed rates."""
    if kpi_df.empty:
        return kpi_df

    result = kpi_df.copy()

    # Compute inadimplência rate: non-performing / total credit rights
    if "DC_PERFORMAR" in result.columns and "DC_NAO_PERFORMAR" in result.columns:
        total_dc = result["DC_PERFORMAR"] + result["DC_NAO_PERFORMAR"]
        result["TAXA_INADIMPLENCIA"] = (
            result["DC_NAO_PERFORMAR"] / total_dc.replace(0, pd.NA) * 100
        )

    # MoM percentage changes — only between truly consecutive months
    if "DT_COMPTC" in result.columns:
        result["DT_COMPTC"] = pd.to_datetime(result["DT_COMPTC"], errors="coerce")
        result = result.sort_values("DT_COMPTC").reset_index(drop=True)
        dates = result["DT_COMPTC"]
        # Check if each row is exactly 1 month after the previous
        month_diff = dates.dt.to_period("M").astype(int).diff()
        is_consecutive = month_diff == 1

        numeric_cols = result.select_dtypes(include="number").columns
        for col in numeric_cols:
            if col == "TAXA_INADIMPLENCIA":
                continue  # Skip rate columns for MoM (already a %)
            pct_col = f"{col}_MoM_%"
            raw_pct = result[col].pct_change(fill_method=None) * 100
            # Null out MoM where months aren't consecutive
            result[pct_col] = raw_pct.where(is_consecutive)

    return result


def _enrich_tables_with_classe(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Enrich tables that lack a CLASSE column by joining with tab_I.

    Many CVM tables (tab_IV, tab_X_2, etc.) have per-class rows identified
    by CNPJ_FUNDO_CLASSE but no CLASSE column. tab_I has both CNPJ_FUNDO_CLASSE
    and CLASSE, so we can join to get class names for pivoting.
    """
    tab_i = tables.get("tab_I")
    if tab_i is None or tab_i.empty:
        return tables

    # Build a CNPJ -> CLASSE mapping from tab_I
    cnpj_col = None
    for c in ["CNPJ_FUNDO_CLASSE", "CNPJ_CLASSE"]:
        if c in tab_i.columns and "CLASSE" in tab_i.columns:
            cnpj_col = c
            break

    if cnpj_col is None or "CLASSE" not in tab_i.columns:
        return tables

    # Create unique CNPJ -> CLASSE + DENOM_SOCIAL mapping
    mapping_cols = [cnpj_col, "CLASSE"]
    if "DENOM_SOCIAL" in tab_i.columns:
        mapping_cols.append("DENOM_SOCIAL")
    classe_map = tab_i[mapping_cols].drop_duplicates(subset=[cnpj_col]).copy()

    enriched = {}
    for tname, tdf in tables.items():
        if tname == "tab_I":
            enriched[tname] = tdf
            continue

        # Only enrich if table has CNPJ col but no CLASSE
        if cnpj_col in tdf.columns and "CLASSE" not in tdf.columns:
            merged = tdf.merge(
                classe_map, on=cnpj_col, how="left", suffixes=("", "_from_tab_I"),
            )
            # If DENOM_SOCIAL already existed, prefer the enriched one (with class suffix)
            if "DENOM_SOCIAL_from_tab_I" in merged.columns:
                # Keep original DENOM_SOCIAL but add the tab_I one as DENOM_SOCIAL
                # only if the original doesn't have class info
                merged["DENOM_SOCIAL"] = merged["DENOM_SOCIAL_from_tab_I"].fillna(
                    merged.get("DENOM_SOCIAL", "")
                )
                merged = merged.drop(columns=["DENOM_SOCIAL_from_tab_I"], errors="ignore")
            enriched[tname] = merged
            added_cols = [c for c in ["CLASSE", "DENOM_SOCIAL"] if c in merged.columns and c not in tdf.columns]
            if added_cols:
                print(f"    Enriched {tname} with {added_cols} from tab_I ({len(merged)} rows)")
        else:
            enriched[tname] = tdf

    return enriched


def extract_per_class_data(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Extract per-class time series for PL and Valor da Cota.

    Returns dict with keys like 'pl_por_classe', 'cota_por_classe',
    each containing a DataFrame with DT_COMPTC as index and one column per class.
    """
    result = {}

    print("\n  Extracting per-class data...")

    # Enrich tables that lack CLASSE with data from tab_I
    # tab_IV, tab_X_2, etc. often have per-class rows (one per CNPJ_FUNDO_CLASSE)
    # but no CLASSE column — only DENOM_SOCIAL with just the fund name.
    # We join with tab_I to get the actual class name.
    enriched_tables = _enrich_tables_with_classe(tables)

    # --- PL por Classe ---
    pl_class_df = _pivot_by_class(
        enriched_tables,
        table_priority=["tab_IV", "tab_I"],
        value_patterns=[r"TAB_IV.*VL_PL", r"VL_PATRIM_LIQ",
                        r"TAB_I2.*PATRIM", r"VL_PL"],
        label="PL",
        agg_func="sum",
    )
    if pl_class_df is not None:
        result["pl_por_classe"] = pl_class_df

    # --- Valor da Cota por Classe ---
    # tab_X_2 has TAB_X_VL_COTA (correct cota values) and TAB_X_CLASSE_SERIE
    # Do NOT search tab_I: TAB_I2C5_VL_COTA_FUNDO_ICVM555 is fund shares held
    # as assets, not the fund's own cota value.
    cota_class_df = _pivot_by_class(
        enriched_tables,
        table_priority=["tab_X_2", "tab_X_3", "tab_X_4"],
        value_patterns=[r"TAB_X_VL_COTA\b", r"TAB_X_VL_COTA$"],
        label="Cota",
        agg_func="mean",
    )
    if cota_class_df is not None:
        result["cota_por_classe"] = cota_class_df

    # --- Rentabilidade por Classe ---
    rentab_class_df = _pivot_by_class(
        enriched_tables,
        table_priority=["tab_X_3", "tab_X_2"],
        value_patterns=[r"TAB_X_VL_RENTAB_MES", r"VL_RENTAB"],
        label="Rentab",
        agg_func="mean",
    )
    if rentab_class_df is not None:
        result["rentab_por_classe"] = rentab_class_df

    # --- NR_COTISTAS por Classe ---
    nr_class_df = _pivot_by_class(
        enriched_tables,
        table_priority=["tab_X_1", "tab_I"],
        value_patterns=[r"TAB_X_NR_COTST\b", r"NR_COTST_TOTAL",
                        r"NR_COTISTAS", r"QT_COTST"],
        label="Cotistas",
        agg_func="max",
    )
    if nr_class_df is not None:
        result["cotistas_por_classe"] = nr_class_df

    if not result:
        print("  WARNING: No per-class data extracted from any table!")
    else:
        print(f"  Per-class extraction complete: {list(result.keys())}")

    return result


def _normalize_class_name(raw_name) -> str:
    """Normalize subclass names to top-level groups.

    Examples:
        'Subclasse Senior Série 3' -> 'Senior'
        'Subclasse Subordinada Mezanino 1 |' -> 'Mezanino'
        'SENIOR' -> 'Senior'
        'Classe Subordinada' -> 'Subordinada'
        'Facio 3 FIDC RL - Subclasse Senior Serie 1' -> 'Senior'
    """
    if raw_name is None or (isinstance(raw_name, float) and pd.isna(raw_name)):
        return "Desconhecida"
    name = str(raw_name).strip().upper()
    # Order matters: check Mezanino before Subordinada since
    # "Subordinada Mezanino" should map to Mezanino
    if "MEZANINO" in name or "MEZZANIN" in name or "MEZZAN" in name:
        return "Mezanino"
    if "SENIOR" in name or "SÊNIOR" in name or "SENIO" in name or "SÊNIO" in name:
        return "Senior"
    if "SUBORDINAD" in name or "JUNIOR" in name or "JÚNIOR" in name or "SUB " in name:
        return "Subordinada"
    # Fallback: return cleaned original
    return raw_name.strip().title()


def _extract_fund_short_name(denom_social: str) -> str:
    """Extract short fund label from DENOM_SOCIAL.

    'Facio 4 Fundo De Investimento Em Direitos Creditórios ...' -> 'Facio 4'
    'Facio 3 FIDC RL - Subclasse Senior Serie 1' -> 'Facio 3'
    'Facio FIDC Financeiros RL' -> 'Facio 1'
    """
    if denom_social is None or (isinstance(denom_social, float) and pd.isna(denom_social)):
        return "Desconhecido"
    name = str(denom_social).strip()
    m = re.search(r"Facio\s*(\d+)", name, re.IGNORECASE)
    if m:
        return f"Facio {m.group(1)}"
    if "facio" in name.lower():
        return "Facio 1"
    return name[:20]


def _pivot_by_class(
    tables: dict[str, pd.DataFrame],
    table_priority: list[str],
    value_patterns: list[str],
    label: str,
    agg_func: str = "sum",
) -> pd.DataFrame | None:
    """Pivot a table by class, producing one column per class over time.

    Searches tables in priority order. Looks for a class identifier column
    and a numeric value column matching the patterns.

    When multiple funds are present, creates combined labels like
    'Facio 3 - Senior', 'Facio 4 - Mezanino'.
    """
    # Possible class identifier columns (order matters: prefer specific over generic)
    class_col_candidates = [
        "CLASSE", "TAB_X_CLASSE_SERIE", "CLASSE_SERIE",
        "TP_CLASSE", "DS_CLASSE", "NM_CLASSE", "DENOM_SOCIAL",
    ]

    for table_name in table_priority:
        df = tables.get(table_name)
        if df is None or df.empty or "DT_COMPTC" not in df.columns:
            print(f"    [{label}] {table_name}: not found or empty, skipping")
            continue

        print(f"    [{label}] trying {table_name} ({len(df)} rows, {len(df.columns)} cols)")

        # Find class column — must have >1 unique value (otherwise no class breakdown)
        class_col = None
        for cc in class_col_candidates:
            if cc in df.columns:
                unique_vals = df[cc].dropna().unique()
                if len(unique_vals) > 1:
                    class_col = cc
                    sample = [str(v)[:60] for v in unique_vals[:6]]
                    print(f"      class_col = '{cc}' ({len(unique_vals)} unique): {sample}")
                    break
                else:
                    val_str = str(unique_vals[0])[:60] if len(unique_vals) == 1 else "empty"
                    print(f"      {cc}: only {len(unique_vals)} unique ({val_str}), skipping")

        if class_col is None:
            # For tab_X_2/3/4, use the table name itself as class identifier
            if table_name.startswith("tab_X_"):
                class_map = {
                    "tab_X_2": "Senior",
                    "tab_X_3": "Mezanino",
                    "tab_X_4": "Subordinada",
                }
                if table_name in class_map:
                    print(f"      Falling back to separate tab_X tables")
                    return _build_from_separate_tables(
                        tables, class_map, value_patterns, label
                    )
            print(f"      No class column found in {table_name}")
            continue

        # Find value column — try each pattern against all columns
        value_col = None
        for col in df.columns:
            for pattern in value_patterns:
                if re.search(pattern, col, re.IGNORECASE):
                    values = pd.to_numeric(df[col], errors="coerce")
                    if not values.isna().all():
                        value_col = col
                        median_val = values.dropna().median()
                        print(f"      value_col = '{col}' (pattern '{pattern}', median={median_val:.2f})")
                        break
            if value_col:
                break

        if value_col is None:
            # Show what columns ARE available for debugging
            all_cols = [c for c in df.columns if c not in (
                "DT_COMPTC", "CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE", "CNPJ_CLASSE",
                "DENOM_SOCIAL", "CLASSE", "TP_CLASSE", "DS_CLASSE", "NM_CLASSE",
                "CLASSE_SERIE", "TAB_X_CLASSE_SERIE", "CLASSE_UNICA",
            )]
            print(f"      NO value column matched! Patterns: {value_patterns}")
            print(f"      Available columns ({len(all_cols)}): {all_cols[:20]}")
            continue

        # Pivot: rows=date, columns=class, values=numeric value
        # Include DENOM_SOCIAL if available for multi-fund labeling
        cols_to_copy = ["DT_COMPTC", class_col, value_col]
        if "DENOM_SOCIAL" in df.columns and "DENOM_SOCIAL" not in cols_to_copy:
            cols_to_copy.append("DENOM_SOCIAL")
        pivot_df = df[cols_to_copy].copy()
        pivot_df[value_col] = pd.to_numeric(pivot_df[value_col], errors="coerce")
        pivot_df = pivot_df.dropna(subset=[value_col, class_col])

        if pivot_df.empty:
            print(f"      Pivot data empty after dropna")
            continue

        # Normalize class names to top-level groups (Senior, Mezanino, Subordinada)
        pivot_df["_classe_grupo"] = pivot_df[class_col].apply(_normalize_class_name)
        unique_classes = pivot_df["_classe_grupo"].unique()
        print(f"      Normalized classes: {list(unique_classes)}")

        # Detect if multiple funds are present (via DENOM_SOCIAL)
        multi_fund = False
        if "DENOM_SOCIAL" in pivot_df.columns:
            fund_names_in_data = pivot_df["DENOM_SOCIAL"].dropna().apply(_extract_fund_short_name).unique()
            multi_fund = len(fund_names_in_data) > 1
            print(f"      multi_fund={multi_fund}, funds={list(fund_names_in_data)}")

        if multi_fund:
            # Create combined fund+class label: "Facio 3 - Senior"
            pivot_df["_fund_short"] = pivot_df["DENOM_SOCIAL"].apply(_extract_fund_short_name)
            pivot_df["_full_label"] = pivot_df["_fund_short"] + " - " + pivot_df["_classe_grupo"]

            pivoted = pivot_df.pivot_table(
                index="DT_COMPTC",
                columns="_full_label",
                values=value_col,
                aggfunc=agg_func,
            )
        else:
            pivoted = pivot_df.pivot_table(
                index="DT_COMPTC",
                columns="_classe_grupo",
                values=value_col,
                aggfunc=agg_func,
            )

        if pivoted.empty or pivoted.columns.empty:
            print(f"      Pivoted result is empty")
            continue

        # Clean column names
        pivoted.columns = [f"{label} - {str(c).strip()}" for c in pivoted.columns]
        # Sort columns for consistent ordering
        sorted_cols = sorted(pivoted.columns)
        pivoted = pivoted[sorted_cols]
        pivoted = pivoted.reset_index().sort_values("DT_COMPTC")

        print(f"  OK Per-class {label}: {len(pivoted)} months, classes: {list(pivoted.columns[1:])}")
        return pivoted

    print(f"  FAILED Per-class {label}: no data found in any table")
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
