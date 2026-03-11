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
    sub_col = next((c for c in pl_df.columns if "Subordinada" in c), None)

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


def compute_performance_metrics(
    kpi_df: pd.DataFrame,
    per_class: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Compute performance metrics including returns and PL evolution."""
    result = kpi_df[["DT_COMPTC"]].copy()

    # PL
    if "PL" in kpi_df.columns:
        result["PL"] = kpi_df["PL"]
        result["PL_MoM_%"] = kpi_df["PL"].pct_change() * 100

    # Total assets
    if "ATIVO_TOTAL" in kpi_df.columns:
        result["Ativo_Total"] = kpi_df["ATIVO_TOTAL"]

    # Monthly return
    if "RENTAB_MES" in kpi_df.columns:
        result["Rentabilidade_%"] = kpi_df["RENTAB_MES"]

    # Quota value
    if "VALOR_COTA" in kpi_df.columns:
        result["Valor_Cota"] = kpi_df["VALOR_COTA"]
        result["Cota_MoM_%"] = kpi_df["VALOR_COTA"].pct_change() * 100

    # Number of quotaholders
    if "NR_COTISTAS" in kpi_df.columns:
        result["Nr_Cotistas"] = kpi_df["NR_COTISTAS"]

    return result


def get_alert_flags(kpi_df: pd.DataFrame, per_class: dict[str, pd.DataFrame]) -> list[dict]:
    """Generate alert flags for concerning metrics.

    Returns list of dicts with keys: level ('danger', 'warning', 'info'), message, metric.
    """
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
            if rate > 15:
                alerts.append({
                    "level": "danger",
                    "message": f"Taxa de inadimplencia alta: {rate:.1f}%",
                    "metric": "TAXA_INADIMPLENCIA",
                })
            elif rate > 10:
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
            if pl_change < -10:
                alerts.append({
                    "level": "danger",
                    "message": f"PL caiu {abs(pl_change):.1f}% no mes",
                    "metric": "PL",
                })
            elif pl_change < -5:
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
            if latest_sub < 10:
                alerts.append({
                    "level": "danger",
                    "message": f"Subordinacao senior baixa: {latest_sub:.1f}%",
                    "metric": "SUBORDINACAO",
                })
            elif latest_sub < 20:
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
