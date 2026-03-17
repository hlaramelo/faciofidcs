"""Advanced analytics for FIDC credit investor monitoring.

Computes derived metrics focused on credit quality, subordination,
and fund performance — the metrics that matter for credit investors.
"""

import pandas as pd
import numpy as np
import requests


def compute_subordination_ratios(per_class: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    """Compute subordination (credit enhancement) ratios.

    Subordination ratio = (Mezanino PL + Subordinada PL) / Total PL
    This measures how much loss buffer exists to protect senior quotaholders.
    """
    pl_df = per_class.get("pl_por_classe")
    if pl_df is None or pl_df.empty:
        return None

    result = pl_df[["DT_COMPTC"]].copy()

    # Find class columns
    senior_col = next((c for c in pl_df.columns if "Senior" in c), None)
    mez_col = next((c for c in pl_df.columns if "Mezanino" in c), None)
    sub_col = next((c for c in pl_df.columns if "Subordinada" in c or "Junior" in c), None)

    # Total PL
    class_cols = [c for c in [senior_col, mez_col, sub_col] if c is not None]
    if len(class_cols) < 2:
        return None

    result["PL_Total"] = pl_df[class_cols].sum(axis=1)

    if senior_col:
        result["PL_Senior"] = pl_df[senior_col]
    if mez_col:
        result["PL_Mezanino"] = pl_df[mez_col]
    if sub_col:
        result["PL_Subordinada"] = pl_df[sub_col]

    # Subordination ratio for senior holders
    # = (everything below senior) / total PL
    below_senior = []
    if mez_col:
        below_senior.append(pl_df[mez_col])
    if sub_col:
        below_senior.append(pl_df[sub_col])

    if below_senior:
        cushion = sum(below_senior)
        result["Subordinacao_Senior_%"] = (cushion / result["PL_Total"].replace(0, np.nan)) * 100

    # Subordination ratio for mezanino holders
    if sub_col and mez_col:
        result["Subordinacao_Mezanino_%"] = (
            pl_df[sub_col] / result["PL_Total"].replace(0, np.nan)
        ) * 100

    # PL share percentages
    for col_name, source_col in [("Senior_%", senior_col), ("Mezanino_%", mez_col), ("Subordinada_%", sub_col)]:
        if source_col:
            result[col_name] = (pl_df[source_col] / result["PL_Total"].replace(0, np.nan)) * 100

    return result


def compute_credit_quality_metrics(kpi_df: pd.DataFrame) -> pd.DataFrame:
    """Compute comprehensive credit quality metrics.

    Returns DataFrame with:
    - Default rate (taxa inadimplencia)
    - Provisioning coverage ratio
    - NPL evolution
    - Credit portfolio composition
    """
    result = kpi_df[["DT_COMPTC"]].copy()
    result["DT_COMPTC"] = pd.to_datetime(result["DT_COMPTC"], errors="coerce")

    perf = kpi_df.get("DC_PERFORMAR")
    non_perf = kpi_df.get("DC_NAO_PERFORMAR")
    inad_vl = kpi_df.get("INADIMPLENCIA_VL")
    provisao = kpi_df.get("INADIMPLENCIA_PROVISAO")

    if perf is not None and non_perf is not None:
        total_dc = perf + non_perf
        result["Carteira_Total"] = total_dc
        result["DC_Performar"] = perf
        result["DC_Nao_Performar"] = non_perf
        result["Taxa_Inadimplencia_%"] = (non_perf / total_dc.replace(0, np.nan)) * 100
        result["Taxa_Adimplencia_%"] = (perf / total_dc.replace(0, np.nan)) * 100

        # MoM change in default rate
        result["Inadimplencia_MoM_pp"] = result["Taxa_Inadimplencia_%"].diff()

    if inad_vl is not None:
        result["Inadimplencia_Valor"] = inad_vl

    if provisao is not None:
        result["Provisao_Perdas"] = provisao

    # Provisioning coverage: provision / non-performing
    if provisao is not None and non_perf is not None:
        result["Cobertura_Provisao_%"] = (
            provisao.abs() / non_perf.replace(0, np.nan)
        ) * 100

    return result


def compute_credit_ratios_vs_pl(kpi_df: pd.DataFrame) -> pd.DataFrame:
    """Compute credit risk ratios relative to PL (Net Equity).

    Returns DataFrame with:
    - Vencidos_x_PL_%: overdue receivables as % of PL
    - Recompra_x_PL_%: buyback activity as % of PL
    - PDD_x_PL_%: provisions for doubtful debts as % of PL
    """
    result = kpi_df[["DT_COMPTC"]].copy()
    result["DT_COMPTC"] = pd.to_datetime(result["DT_COMPTC"], errors="coerce")

    pl = kpi_df.get("PL")
    if pl is None:
        return result

    pl_safe = pl.replace(0, np.nan)

    # Vencidos x PL: overdue receivables / PL
    # Try VENCIDOS_VL first, fall back to INADIMPLENCIA_VL
    vencidos = kpi_df.get("VENCIDOS_VL")
    if vencidos is None:
        vencidos = kpi_df.get("INADIMPLENCIA_VL")
    if vencidos is not None:
        result["Vencidos_x_PL_%"] = (vencidos.abs() / pl_safe) * 100

    # Recompra x PL: buyback / PL
    recompra = kpi_df.get("RECOMPRA_VL")
    if recompra is not None:
        result["Recompra_x_PL_%"] = (recompra.abs() / pl_safe) * 100

    # PDD x PL: provisions / PL
    pdd = kpi_df.get("INADIMPLENCIA_PROVISAO")
    if pdd is not None:
        result["PDD_x_PL_%"] = (pdd.abs() / pl_safe) * 100

    return result


def compute_flow_metrics(kpi_df: pd.DataFrame) -> pd.DataFrame:
    """Compute portfolio flow metrics (acquisitions, redemptions, net flow)."""
    result = kpi_df[["DT_COMPTC"]].copy()

    aquis = kpi_df.get("AQUISICOES")
    resg = kpi_df.get("RESGATES")
    subst = kpi_df.get("SUBSTITUICAO")

    if aquis is not None:
        result["Aquisicoes"] = aquis
    if resg is not None:
        result["Resgates"] = resg
    if subst is not None:
        result["Substituicoes"] = subst

    # Net flow
    if aquis is not None and resg is not None:
        result["Fluxo_Liquido"] = aquis.fillna(0) - resg.fillna(0).abs()

    return result


def compute_pl_waterfall(kpi_df: pd.DataFrame) -> pd.DataFrame | None:
    """Decompose PL changes into contributing factors.

    Returns DataFrame with columns: DT_COMPTC, PL_Change, Rendimentos,
    Aquisicoes, Resgates, Inadimplencia, Outros.
    """
    if "PL" not in kpi_df.columns or len(kpi_df) < 2:
        return None

    result = kpi_df[["DT_COMPTC"]].copy()
    result["PL"] = kpi_df["PL"]
    result["PL_Anterior"] = kpi_df["PL"].shift(1)
    result["Variacao_PL"] = result["PL"] - result["PL_Anterior"]

    # Decompose into known drivers
    result["Rendimentos"] = np.nan
    if "RENTAB_MES" in kpi_df.columns:
        # Estimated return: previous PL * monthly return %
        result["Rendimentos"] = result["PL_Anterior"] * kpi_df["RENTAB_MES"].fillna(0) / 100

    result["Aquisicoes"] = kpi_df.get("AQUISICOES", pd.Series(dtype=float)).fillna(0).values
    result["Resgates"] = -kpi_df.get("RESGATES", pd.Series(dtype=float)).fillna(0).abs().values
    result["Inadimplencia"] = -kpi_df.get("INADIMPLENCIA_VL", pd.Series(dtype=float)).fillna(0).abs().values

    # "Outros" = total change minus known factors
    known = result["Rendimentos"].fillna(0) + result["Aquisicoes"] + result["Resgates"] + result["Inadimplencia"]
    result["Outros"] = result["Variacao_PL"] - known

    # Drop first row (no previous PL)
    result = result.iloc[1:].reset_index(drop=True)

    # Only return if we have some meaningful data
    if result["Variacao_PL"].isna().all():
        return None

    return result


def compute_performance_metrics(
    kpi_df: pd.DataFrame,
    per_class: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Compute performance metrics including returns and PL evolution."""
    result = kpi_df[["DT_COMPTC"]].copy()

    # PL
    if "PL" in kpi_df.columns:
        result["PL"] = kpi_df["PL"]
        result["PL_MoM_%"] = kpi_df["PL"].pct_change(fill_method=None) * 100

    # Total assets
    if "ATIVO_TOTAL" in kpi_df.columns:
        result["Ativo_Total"] = kpi_df["ATIVO_TOTAL"]

    # Monthly return
    if "RENTAB_MES" in kpi_df.columns:
        result["Rentabilidade_%"] = kpi_df["RENTAB_MES"]

    # Quota value
    if "VALOR_COTA" in kpi_df.columns:
        result["Valor_Cota"] = kpi_df["VALOR_COTA"]
        result["Cota_MoM_%"] = kpi_df["VALOR_COTA"].pct_change(fill_method=None) * 100

    # Number of quotaholders
    if "NR_COTISTAS" in kpi_df.columns:
        result["Nr_Cotistas"] = kpi_df["NR_COTISTAS"]

    return result


def get_alert_flags(
    kpi_df: pd.DataFrame,
    per_class: dict[str, pd.DataFrame],
    thresholds: dict | None = None,
) -> list[dict]:
    """Generate alert flags for concerning metrics.

    Returns list of dicts with keys: level ('danger', 'warning', 'info'), message, metric.
    thresholds: optional dict with keys inad_danger, inad_warning, pl_danger, sub_danger, sub_warning.
    """
    t = thresholds or {}
    inad_danger = t.get("inad_danger", 15)
    inad_warning = t.get("inad_warning", 10)
    pl_danger = t.get("pl_danger", 10)
    sub_danger = t.get("sub_danger", 10)
    sub_warning = t.get("sub_warning", 20)

    alerts = []
    if kpi_df.empty or len(kpi_df) < 2:
        return alerts

    latest = kpi_df.iloc[-1]
    prev = kpi_df.iloc[-2]

    # 1. Default rate alerts
    if "TAXA_INADIMPLENCIA" in kpi_df.columns:
        rate = latest.get("TAXA_INADIMPLENCIA")
        prev_rate = prev.get("TAXA_INADIMPLENCIA")
        if pd.notna(rate):
            if rate > inad_danger:
                alerts.append({
                    "level": "danger",
                    "message": f"Taxa de inadimplencia alta: {rate:.1f}%",
                    "metric": "TAXA_INADIMPLENCIA",
                })
            elif rate > inad_warning:
                alerts.append({
                    "level": "warning",
                    "message": f"Taxa de inadimplencia elevada: {rate:.1f}%",
                    "metric": "TAXA_INADIMPLENCIA",
                })

            if pd.notna(prev_rate) and prev_rate > 0:
                change = rate - prev_rate
                if change > 2:
                    alerts.append({
                        "level": "danger",
                        "message": f"Inadimplencia subiu {change:.1f}pp no mes",
                        "metric": "TAXA_INADIMPLENCIA",
                    })
                elif change > 1:
                    alerts.append({
                        "level": "warning",
                        "message": f"Inadimplencia subiu {change:.1f}pp no mes",
                        "metric": "TAXA_INADIMPLENCIA",
                    })

    # 2. PL drop
    if "PL" in kpi_df.columns:
        pl = latest.get("PL")
        prev_pl = prev.get("PL")
        if pd.notna(pl) and pd.notna(prev_pl) and prev_pl > 0:
            pl_change = (pl - prev_pl) / prev_pl * 100
            if pl_change < -pl_danger:
                alerts.append({
                    "level": "danger",
                    "message": f"PL caiu {abs(pl_change):.1f}% no mes",
                    "metric": "PL",
                })
            elif pl_change < -(pl_danger / 2):
                alerts.append({
                    "level": "warning",
                    "message": f"PL caiu {abs(pl_change):.1f}% no mes",
                    "metric": "PL",
                })

    # 3. Subordination
    sub_df = compute_subordination_ratios(per_class)
    if sub_df is not None and "Subordinacao_Senior_%" in sub_df.columns and len(sub_df) > 0:
        latest_sub = sub_df.iloc[-1].get("Subordinacao_Senior_%")
        if pd.notna(latest_sub):
            if latest_sub < sub_danger:
                alerts.append({
                    "level": "danger",
                    "message": f"Subordinacao senior baixa: {latest_sub:.1f}%",
                    "metric": "SUBORDINACAO",
                })
            elif latest_sub < sub_warning:
                alerts.append({
                    "level": "warning",
                    "message": f"Subordinacao senior em atencao: {latest_sub:.1f}%",
                    "metric": "SUBORDINACAO",
                })

    # 4. Quotaholder concentration
    if "NR_COTISTAS" in kpi_df.columns:
        nr = latest.get("NR_COTISTAS")
        if pd.notna(nr) and nr < 5:
            alerts.append({
                "level": "warning",
                "message": f"Poucos cotistas: {int(nr)}",
                "metric": "NR_COTISTAS",
            })

    # 5. Negative net flow
    aquis = latest.get("AQUISICOES", 0) or 0
    resg = abs(latest.get("RESGATES", 0) or 0)
    if resg > 0 and aquis > 0:
        if resg > aquis * 1.5:
            alerts.append({
                "level": "warning",
                "message": "Resgates superaram aquisicoes significativamente",
                "metric": "FLUXO",
            })

    if not alerts:
        alerts.append({
            "level": "info",
            "message": "Nenhum alerta identificado — indicadores dentro da normalidade",
            "metric": "GERAL",
        })

    return alerts


def compute_covenant_timeline(
    kpi_df: pd.DataFrame,
    per_class: dict[str, pd.DataFrame],
    thresholds: dict | None = None,
) -> pd.DataFrame | None:
    """Track covenant compliance over time.

    Returns DataFrame with DT_COMPTC and boolean columns for each covenant:
    True = compliant, False = breached.
    """
    if kpi_df.empty or "DT_COMPTC" not in kpi_df.columns:
        return None

    t = thresholds or {}
    max_inad = t.get("inad_danger", 15.0)
    min_sub = t.get("sub_danger", 10.0)
    max_pl_drop = t.get("pl_danger", 10.0)

    result = kpi_df[["DT_COMPTC"]].copy()

    # Covenant 1: Inadimplência below threshold
    if "TAXA_INADIMPLENCIA" in kpi_df.columns:
        result[f"Inadimp < {max_inad:.0f}%"] = kpi_df["TAXA_INADIMPLENCIA"].apply(
            lambda x: True if pd.isna(x) else x <= max_inad
        )

    # Covenant 2: Subordination above minimum
    sub_df = compute_subordination_ratios(per_class)
    if sub_df is not None and "Subordinacao_Senior_%" in sub_df.columns:
        merged = result.merge(
            sub_df[["DT_COMPTC", "Subordinacao_Senior_%"]], on="DT_COMPTC", how="left"
        )
        result[f"Subord > {min_sub:.0f}%"] = merged["Subordinacao_Senior_%"].apply(
            lambda x: True if pd.isna(x) else x >= min_sub
        )

    # Covenant 3: PL not declining more than threshold MoM
    if "PL" in kpi_df.columns:
        pl_pct = kpi_df["PL"].pct_change(fill_method=None) * 100
        result[f"PL queda < {max_pl_drop:.0f}%"] = pl_pct.apply(
            lambda x: True if pd.isna(x) else x >= -max_pl_drop
        )

    # Covenant 4: Positive net flow
    if "AQUISICOES" in kpi_df.columns and "RESGATES" in kpi_df.columns:
        net = kpi_df["AQUISICOES"].fillna(0) - kpi_df["RESGATES"].fillna(0).abs()
        result["Fluxo positivo"] = net >= 0

    # Overall compliance
    cov_cols = [c for c in result.columns if c != "DT_COMPTC"]
    if cov_cols:
        result["Compliant"] = result[cov_cols].all(axis=1)
    else:
        return None

    return result


def compute_maturity_buckets(tables: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    """Extract maturity bucketing data from tab_V (credit rights by maturity).

    CVM tab_V contains credit rights broken down by remaining maturity.
    Returns DataFrame with DT_COMPTC and columns for each maturity bucket.
    """
    import re

    # Find tab_V tables
    tab_v_df = None
    for name, df in (tables or {}).items():
        if re.match(r"tab_V\b", name, re.IGNORECASE) or "tab_V" in name:
            tab_v_df = df
            break

    if tab_v_df is None or tab_v_df.empty:
        return None

    if "DT_COMPTC" not in tab_v_df.columns:
        return None

    # Look for maturity-related columns (prazo, vencimento, faixa)
    maturity_cols = [
        c for c in tab_v_df.columns
        if re.search(r"(PRAZO|VENC|FAIXA|BUCKET|VL_)", c, re.IGNORECASE)
        and c not in ("DT_COMPTC", "CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE", "DENOM_SOCIAL")
    ]

    if not maturity_cols:
        # Try to detect value columns (anything numeric that's not an ID)
        id_cols = {"DT_COMPTC", "CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE", "DENOM_SOCIAL", "CLASSE"}
        for c in tab_v_df.columns:
            if c not in id_cols:
                try:
                    pd.to_numeric(tab_v_df[c], errors="raise")
                    maturity_cols.append(c)
                except (ValueError, TypeError):
                    pass

    if not maturity_cols:
        return None

    result = tab_v_df[["DT_COMPTC"] + maturity_cols].copy()
    result["DT_COMPTC"] = pd.to_datetime(result["DT_COMPTC"], errors="coerce")

    # Convert value columns to numeric
    for c in maturity_cols:
        result[c] = pd.to_numeric(result[c], errors="coerce")

    # Group by date (sum across rows for same date, e.g. multiple classes)
    result = result.groupby("DT_COMPTC", as_index=False)[maturity_cols].sum()
    result = result.sort_values("DT_COMPTC").reset_index(drop=True)

    # Clean column names for display
    rename_map = {}
    for c in maturity_cols:
        clean = (
            c.replace("TAB_V_", "")
            .replace("TAB_V1_", "")
            .replace("VL_", "")
            .replace("_", " ")
            .title()
        )
        rename_map[c] = clean
    result = result.rename(columns=rename_map)

    return result


def fetch_cdi_monthly(start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch monthly CDI accumulated rate from BCB SGS API.

    Series 4391 = CDI monthly accumulated rate (%).
    start_date/end_date in 'DD/MM/YYYY' format.
    Returns DataFrame with columns [DT_COMPTC, CDI_%].
    """
    url = (
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.4391/dados"
        f"?formato=json&dataInicial={start_date}&dataFinal={end_date}"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return pd.DataFrame(columns=["DT_COMPTC", "CDI_%"])

    if not data:
        return pd.DataFrame(columns=["DT_COMPTC", "CDI_%"])

    df = pd.DataFrame(data)
    df["DT_COMPTC"] = pd.to_datetime(df["data"], format="%d/%m/%Y")
    df["CDI_%"] = pd.to_numeric(df["valor"], errors="coerce")
    return df[["DT_COMPTC", "CDI_%"]].sort_values("DT_COMPTC").reset_index(drop=True)


def compute_cdi_spread(
    perf_metrics: pd.DataFrame,
    cdi_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute spread (excess return) of fund over CDI.

    Returns DataFrame with columns:
    - DT_COMPTC, Rentabilidade_%, CDI_%, Spread_bps, Spread_%
    - Acumulado_Fundo_%, Acumulado_CDI_%, Acumulado_Spread_bps
    - Retorno_3M_%, Retorno_6M_%, Retorno_12M_%, Retorno_YTD_%
    """
    if perf_metrics.empty or "Rentabilidade_%" not in perf_metrics.columns:
        return pd.DataFrame()

    result = perf_metrics[["DT_COMPTC"]].copy()
    result["Rentabilidade_%"] = perf_metrics["Rentabilidade_%"]

    # Merge CDI
    cdi_available = False
    if cdi_df is not None and not cdi_df.empty and "CDI_%" in cdi_df.columns:
        merged = result.merge(cdi_df[["DT_COMPTC", "CDI_%"]], on="DT_COMPTC", how="left")
        result["CDI_%"] = merged["CDI_%"]
        cdi_available = result["CDI_%"].notna().any()

    if cdi_available:
        result["Spread_%"] = result["Rentabilidade_%"] - result["CDI_%"]
        result["Spread_bps"] = result["Spread_%"] * 100  # 1% = 100 bps

    # Cumulative returns (compounded)
    rentab = result["Rentabilidade_%"].fillna(0) / 100
    result["Acumulado_Fundo_%"] = ((1 + rentab).cumprod() - 1) * 100

    if cdi_available:
        cdi_r = result["CDI_%"].fillna(0) / 100
        result["Acumulado_CDI_%"] = ((1 + cdi_r).cumprod() - 1) * 100
        result["Acumulado_Spread_bps"] = (
            result["Acumulado_Fundo_%"] - result["Acumulado_CDI_%"]
        ) * 100

    # Rolling returns (3M, 6M, 12M)
    for window, label in [(3, "3M"), (6, "6M"), (12, "12M")]:
        if len(result) >= window:
            rolling = (1 + rentab).rolling(window).apply(lambda x: x.prod() - 1, raw=True) * 100
            result[f"Retorno_{label}_%"] = rolling

    # Rolling volatility (annualized std of monthly returns)
    for window, label in [(6, "6M"), (12, "12M")]:
        if len(result) >= window:
            result[f"Vol_{label}_%"] = rentab.rolling(window).std() * np.sqrt(12) * 100

    # Sharpe ratio (annualized, using CDI as risk-free rate)
    if cdi_available:
        excess = rentab - result["CDI_%"].fillna(0) / 100
        for window, label in [(6, "6M"), (12, "12M")]:
            if len(result) >= window:
                roll_mean = excess.rolling(window).mean() * 12
                roll_std = excess.rolling(window).std() * np.sqrt(12)
                result[f"Sharpe_{label}"] = roll_mean / roll_std.replace(0, np.nan)

    # YTD return
    result["_year"] = result["DT_COMPTC"].dt.year
    ytd_values = []
    for _, group in result.groupby("_year"):
        ytd = ((1 + group["Rentabilidade_%"].fillna(0) / 100).cumprod() - 1) * 100
        ytd_values.append(ytd)
    result["Retorno_YTD_%"] = pd.concat(ytd_values).sort_index()
    result = result.drop(columns=["_year"])

    return result


def compute_data_quality(kpi_df: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> dict:
    """Compute data quality metrics for the loaded data.

    Returns dict with:
    - completeness_pct: % of non-null KPI fields
    - missing_kpis: list of KPI names that are entirely missing
    - available_kpis: list of KPI names with data
    - months_with_gaps: list of months where data may be incomplete
    - total_months: total months in dataset
    """
    key_kpis = [
        "PL", "ATIVO_TOTAL", "VALOR_COTA", "NR_COTISTAS",
        "DC_PERFORMAR", "DC_NAO_PERFORMAR", "RENTAB_MES",
        "AQUISICOES", "RESGATES",
    ]

    available = [k for k in key_kpis if k in kpi_df.columns and kpi_df[k].notna().any()]
    missing = [k for k in key_kpis if k not in available]

    total_cells = len(key_kpis) * len(kpi_df)
    filled_cells = sum(
        kpi_df[k].notna().sum() if k in kpi_df.columns else 0
        for k in key_kpis
    )
    completeness = (filled_cells / total_cells * 100) if total_cells > 0 else 0

    # Detect months with many missing fields
    months_with_gaps = []
    if "DT_COMPTC" in kpi_df.columns:
        for _, row in kpi_df.iterrows():
            missing_count = sum(1 for k in available if pd.isna(row.get(k)))
            if missing_count > len(available) * 0.3:
                months_with_gaps.append(row["DT_COMPTC"])

    # Detect data anomalies
    anomalies = []
    if "PL" in kpi_df.columns:
        neg_pl = kpi_df[kpi_df["PL"] < 0]
        if not neg_pl.empty:
            dates = neg_pl["DT_COMPTC"].dt.strftime("%Y-%m").tolist()
            anomalies.append(f"PL negativo em {', '.join(dates)}")

    if "TAXA_INADIMPLENCIA" in kpi_df.columns:
        over100 = kpi_df[kpi_df["TAXA_INADIMPLENCIA"] > 100]
        if not over100.empty:
            dates = over100["DT_COMPTC"].dt.strftime("%Y-%m").tolist()
            anomalies.append(f"Inadimplencia > 100% em {', '.join(dates)}")

    if "VALOR_COTA" in kpi_df.columns:
        neg_cota = kpi_df[kpi_df["VALOR_COTA"] < 0]
        if not neg_cota.empty:
            dates = neg_cota["DT_COMPTC"].dt.strftime("%Y-%m").tolist()
            anomalies.append(f"Valor da cota negativo em {', '.join(dates)}")

    if "RENTAB_MES" in kpi_df.columns:
        extreme = kpi_df[kpi_df["RENTAB_MES"].abs() > 50]
        if not extreme.empty:
            dates = extreme["DT_COMPTC"].dt.strftime("%Y-%m").tolist()
            anomalies.append(f"Rentabilidade mensal > 50% em {', '.join(dates)}")

    if "NR_COTISTAS" in kpi_df.columns:
        nr = kpi_df["NR_COTISTAS"].dropna()
        if len(nr) >= 3:
            # Flag if cotistas count changes by more than 5x in one month
            ratio = nr / nr.shift(1)
            spikes = ratio[(ratio > 5) | (ratio < 0.2)].dropna()
            if not spikes.empty:
                spike_dates = kpi_df.loc[spikes.index, "DT_COMPTC"].dt.strftime("%Y-%m").tolist()
                anomalies.append(f"Variacao brusca de cotistas em {', '.join(spike_dates)}")

    # Detect month gaps in the time series
    date_gaps = []
    if "DT_COMPTC" in kpi_df.columns and len(kpi_df) >= 2:
        dates = pd.to_datetime(kpi_df["DT_COMPTC"]).sort_values()
        periods = dates.dt.to_period("M").astype(int)
        diffs = periods.diff().dropna()
        gap_mask = diffs > 1
        if gap_mask.any():
            for idx in diffs[gap_mask].index:
                gap_start = dates.iloc[dates.index.get_loc(idx) - 1].strftime("%Y-%m")
                gap_end = dates.loc[idx].strftime("%Y-%m")
                gap_months = int(diffs.loc[idx]) - 1
                date_gaps.append(f"{gap_start} → {gap_end} ({gap_months} meses sem dados)")

    return {
        "completeness_pct": completeness,
        "missing_kpis": missing,
        "available_kpis": available,
        "months_with_gaps": months_with_gaps,
        "total_months": len(kpi_df),
        "total_tables": len(tables) if tables else 0,
        "anomalies": anomalies,
        "date_gaps": date_gaps,
    }


def format_brl(value: float | None) -> str:
    """Format a number as BRL currency string."""
    if value is None or pd.isna(value):
        return "—"
    if abs(value) >= 1_000_000_000:
        return f"R$ {value / 1_000_000_000:,.2f} bi"
    if abs(value) >= 1_000_000:
        return f"R$ {value / 1_000_000:,.2f} mi"
    if abs(value) >= 1_000:
        return f"R$ {value / 1_000:,.2f} mil"
    return f"R$ {value:,.2f}"


def format_pct(value: float | None, decimals: int = 2) -> str:
    """Format a number as percentage string."""
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.{decimals}f}%"
