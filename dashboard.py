#!/usr/bin/env python3
"""Facio FIDC Monitoring Dashboard — Professional credit investor view.

Run with: streamlit run dashboard.py
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from config import DATA_DIR, FUNDS
from src.analytics import (
    compute_cdi_spread,
    compute_credit_quality_metrics,
    compute_data_quality,
    compute_flow_metrics,
    compute_performance_metrics,
    compute_pl_waterfall,
    compute_subordination_ratios,
    fetch_cdi_monthly,
    format_brl,
    format_pct,
    get_alert_flags,
)
from src.data_cache import (
    clear_cache,
    clear_raw_months,
    is_cache_valid,
    load_from_cache,
    needs_incremental_update,
    save_to_cache,
)
from src.downloader import download_monthly_zips
from src.kpi_extractor import compute_trends, extract_kpis, extract_per_class_data
from src.parser import parse_all_tables

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Facio FIDC Monitor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Clean professional look */
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }

    /* Metric cards */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #f8f9fc 0%, #ffffff 100%);
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    div[data-testid="stMetric"] label {
        font-size: 0.8rem !important;
        color: #64748b !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        color: #1e293b !important;
    }

    /* Alert boxes */
    .alert-danger {
        background: #fef2f2; border-left: 4px solid #ef4444;
        padding: 12px 16px; border-radius: 6px; margin: 4px 0;
        color: #991b1b; font-weight: 500;
    }
    .alert-warning {
        background: #fffbeb; border-left: 4px solid #f59e0b;
        padding: 12px 16px; border-radius: 6px; margin: 4px 0;
        color: #92400e; font-weight: 500;
    }
    .alert-info {
        background: #f0fdf4; border-left: 4px solid #22c55e;
        padding: 12px 16px; border-radius: 6px; margin: 4px 0;
        color: #166534; font-weight: 500;
    }

    /* Section headers */
    .section-header {
        font-size: 1.1rem; font-weight: 600; color: #1e293b;
        border-bottom: 2px solid #3b82f6; padding-bottom: 6px;
        margin-bottom: 16px; margin-top: 8px;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #1e293b;
    }
    section[data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }

    /* Hide default menu */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0 0;
        padding: 8px 20px;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

# ── Chart theme ──────────────────────────────────────────────────────────────

def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """Convert a hex color like '#3b82f6' to 'rgba(r,g,b,a)' for plotly."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


COLORS = {
    "primary": "#3b82f6",
    "success": "#22c55e",
    "danger": "#ef4444",
    "warning": "#f59e0b",
    "info": "#06b6d4",
    "muted": "#94a3b8",
    "senior": "#3b82f6",
    "mezanino": "#f59e0b",
    "subordinada": "#ef4444",
}

CHART_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Inter, system-ui, sans-serif", size=12, color="#334155"),
    title_font=dict(size=15, color="#1e293b"),
    legend=dict(orientation="h", yanchor="top", y=-0.35, xanchor="center", x=0.5),
    margin=dict(l=40, r=20, t=50, b=80),
    hovermode="x unified",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
)


def styled_line_chart(df, x, y_cols, title, y_format=None, colors=None):
    """Create a clean line chart."""
    fig = go.Figure()
    palette = colors or [COLORS["primary"], COLORS["warning"], COLORS["danger"], COLORS["info"]]
    valid_cols = [c for c in y_cols if c in df.columns]
    # Filter to rows where at least one y column has data
    if valid_cols:
        plot_df = df.dropna(subset=valid_cols, how="all")
    else:
        plot_df = df
    for i, col in enumerate(valid_cols):
        fig.add_trace(go.Scatter(
            x=plot_df[x], y=plot_df[col], name=col, mode="lines+markers",
            line=dict(color=palette[i % len(palette)], width=2.5),
            marker=dict(size=5),
        ))
    fig.update_layout(**CHART_LAYOUT, title=title)
    if y_format == "brl":
        fig.update_yaxes(tickformat=",.0f", tickprefix="R$ ")
    elif y_format == "pct":
        fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
    return fig


def styled_bar_chart(df, x, y_cols, title, y_format=None, colors=None, barmode="group"):
    """Create a clean bar chart."""
    fig = go.Figure()
    palette = colors or [COLORS["primary"], COLORS["success"], COLORS["danger"], COLORS["warning"]]
    valid_cols = [c for c in y_cols if c in df.columns]
    plot_df = df.dropna(subset=valid_cols, how="all") if valid_cols else df
    for i, col in enumerate(valid_cols):
        fig.add_trace(go.Bar(
            x=plot_df[x], y=plot_df[col], name=col,
            marker_color=palette[i % len(palette)],
            opacity=0.9,
        ))
    fig.update_layout(**CHART_LAYOUT, title=title, barmode=barmode)
    if y_format == "brl":
        fig.update_yaxes(tickformat=",.0f", tickprefix="R$ ")
    elif y_format == "pct":
        fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
    return fig


def styled_area_chart(df, x, y_cols, title, y_format=None, colors=None):
    """Create a clean stacked area chart with stackgroup for proper stacking."""
    fig = go.Figure()
    palette = colors or [COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]]
    valid_cols = [c for c in y_cols if c in df.columns]
    plot_df = df.dropna(subset=valid_cols, how="all") if valid_cols else df
    for i, col in enumerate(valid_cols):
        fig.add_trace(go.Scatter(
            x=plot_df[x], y=plot_df[col].fillna(0), name=col, mode="lines",
            stackgroup="one",
            line=dict(color=palette[i % len(palette)], width=1),
            fillcolor=_hex_to_rgba(palette[i % len(palette)], 0.4),
        ))
    fig.update_layout(**CHART_LAYOUT, title=title)
    if y_format == "brl":
        fig.update_yaxes(tickformat=",.0f", tickprefix="R$ ")
    elif y_format == "pct":
        fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
    return fig


# ── Data loading ─────────────────────────────────────────────────────────────

def _process_fund_data(start_str: str, end_str: str, cnpj_raw: str, fund_display_name: str = ""):
    """Download, parse, and extract KPIs for a single fund from CVM source."""
    from datetime import date as d

    start_parts = start_str.split("-")
    end_parts = end_str.split("-")
    start_date = d(int(start_parts[0]), int(start_parts[1]), 1)
    end_date = d(int(end_parts[0]), int(end_parts[1]), 1)

    data_dirs = download_monthly_zips(start_date, end_date)
    if not data_dirs:
        return None, None, None, None

    # Pass fund name for DENOM_SOCIAL fallback filtering
    fund_names_hint = [fund_display_name] if fund_display_name else None
    tables = parse_all_tables(data_dirs, [cnpj_raw], fund_names=fund_names_hint)
    if not tables:
        return None, None, None, None

    kpi_df = extract_kpis(tables)
    if kpi_df.empty:
        return None, None, None, None

    kpi_df = compute_trends(kpi_df)
    per_class = extract_per_class_data(tables)

    # Fetch CDI benchmark
    cdi_start = f"01/{start_parts[1]}/{start_parts[0]}"
    cdi_end = f"28/{end_parts[1]}/{end_parts[0]}"
    cdi_df = fetch_cdi_monthly(cdi_start, cdi_end)

    # Save to persistent cache
    save_to_cache(cnpj_raw, start_str, end_str, kpi_df, tables, per_class, cdi_df)

    return kpi_df, tables, per_class, cdi_df


def load_data(start_str: str, end_str: str, cnpj_raw: str, fund_display_name: str = "", force_refresh: bool = False):
    """Load KPIs for a single fund, using persistent cache when available.

    Data is loaded from parquet cache unless:
    - force_refresh=True (user clicked Atualizar Dados)
    - Cache doesn't exist (first run)
    - Date range changed
    """
    if not force_refresh and is_cache_valid(cnpj_raw, start_str, end_str):
        print(f"  Loading {fund_display_name or cnpj_raw} from cache...")
        return load_from_cache(cnpj_raw)

    print(f"  Processing {fund_display_name or cnpj_raw} from CVM data...")
    return _process_fund_data(start_str, end_str, cnpj_raw, fund_display_name)


def load_consolidated_data(start_str: str, end_str: str, force_refresh: bool = False):
    """Load and consolidate KPIs across all Facio funds."""
    import numpy as np

    all_kpis = []
    all_tables = {}
    cdi_df_out = None

    for fund in FUNDS:
        result = load_data(start_str, end_str, fund["cnpj_raw"], fund["name"], force_refresh=force_refresh)
        kpi, tables, per_class, cdi = result
        if tables:
            for tname, tdf in tables.items():
                key = f"{tname} ({fund['name']})"
                all_tables[key] = tdf
        if kpi is not None and not kpi.empty:
            # Tag each row with fund name
            kpi_copy = kpi.copy()
            kpi_copy["_fund_name"] = fund["name"]
            all_kpis.append(kpi_copy)
        if cdi is not None and not cdi.empty:
            cdi_df_out = cdi

    if not all_kpis:
        return None, None, None, cdi_df_out

    combined = pd.concat(all_kpis, ignore_index=True)

    # Aggregate: sum additive columns, per date
    sum_cols = [c for c in [
        "PL", "ATIVO_TOTAL", "DC_PERFORMAR", "DC_NAO_PERFORMAR",
        "AQUISICOES", "RESGATES", "INADIMPLENCIA_VL", "INADIMPLENCIA_PROVISAO",
        "SUBSTITUICAO",
    ] if c in combined.columns]

    # NR_COTISTAS: sum across funds (each fund contributes its own cotistas)
    nr_sum_cols = [c for c in ["NR_COTISTAS"] if c in combined.columns]

    agg_dict = {}
    for c in sum_cols:
        agg_dict[c] = "sum"
    for c in nr_sum_cols:
        agg_dict[c] = "sum"
    # VALOR_COTA: not meaningful to average across funds with different cota values
    # RENTAB_MES: compute PL-weighted average below instead of simple mean

    consolidated = combined.groupby("DT_COMPTC", as_index=False).agg(agg_dict)
    consolidated = consolidated.sort_values("DT_COMPTC").reset_index(drop=True)

    # Compute PL-weighted RENTAB_MES for consolidated view
    if "RENTAB_MES" in combined.columns and "PL" in combined.columns:
        def _weighted_mean_rentab(group):
            valid = group.dropna(subset=["RENTAB_MES", "PL"])
            if valid.empty or valid["PL"].sum() == 0:
                return np.nan
            return (valid["RENTAB_MES"] * valid["PL"]).sum() / valid["PL"].sum()
        wm = combined.groupby("DT_COMPTC").apply(_weighted_mean_rentab).reset_index()
        wm.columns = ["DT_COMPTC", "RENTAB_MES"]
        consolidated = consolidated.merge(wm, on="DT_COMPTC", how="left")
    elif "RENTAB_MES" in combined.columns:
        rm = combined.groupby("DT_COMPTC")["RENTAB_MES"].mean().reset_index()
        consolidated = consolidated.merge(rm, on="DT_COMPTC", how="left")

    # VALOR_COTA: use PL-weighted average (funds with higher PL weigh more)
    if "VALOR_COTA" in combined.columns and "PL" in combined.columns:
        def _weighted_mean_cota(group):
            valid = group.dropna(subset=["VALOR_COTA", "PL"])
            if valid.empty or valid["PL"].sum() == 0:
                return np.nan
            return (valid["VALOR_COTA"] * valid["PL"]).sum() / valid["PL"].sum()
        wc = combined.groupby("DT_COMPTC").apply(_weighted_mean_cota).reset_index()
        wc.columns = ["DT_COMPTC", "VALOR_COTA"]
        consolidated = consolidated.merge(wc, on="DT_COMPTC", how="left")

    # Recompute derived rate columns after aggregation
    if "DC_PERFORMAR" in consolidated.columns and "DC_NAO_PERFORMAR" in consolidated.columns:
        total_dc = consolidated["DC_PERFORMAR"] + consolidated["DC_NAO_PERFORMAR"]
        consolidated["TAXA_INADIMPLENCIA"] = (
            consolidated["DC_NAO_PERFORMAR"] / total_dc.replace(0, np.nan) * 100
        )

    # MoM changes — only between consecutive months
    consolidated = consolidated.sort_values("DT_COMPTC").reset_index(drop=True)
    cons_dates = pd.to_datetime(consolidated["DT_COMPTC"])
    cons_month_diff = cons_dates.dt.to_period("M").astype(int).diff()
    cons_is_consecutive = cons_month_diff == 1
    for col in consolidated.select_dtypes(include="number").columns:
        if col == "TAXA_INADIMPLENCIA":
            continue
        raw_pct = consolidated[col].pct_change(fill_method=None) * 100
        consolidated[f"{col}_MoM_%"] = raw_pct.where(cons_is_consecutive)

    # Build per-fund breakdowns for consolidated per_class
    cons_per_class = {}

    # PL by fund
    pl_by_fund = combined.pivot_table(
        index="DT_COMPTC", columns="_fund_name", values="PL", aggfunc="sum",
    )
    if not pl_by_fund.empty:
        pl_by_fund = pl_by_fund.reset_index().sort_values("DT_COMPTC")
        pl_by_fund.columns = ["DT_COMPTC"] + [f"PL - {c}" for c in pl_by_fund.columns[1:]]
        cons_per_class["pl_por_classe"] = pl_by_fund

    # Cota by fund (each fund has its own cota value)
    if "VALOR_COTA" in combined.columns:
        cota_by_fund = combined.pivot_table(
            index="DT_COMPTC", columns="_fund_name", values="VALOR_COTA", aggfunc="mean",
        )
        if not cota_by_fund.empty:
            cota_by_fund = cota_by_fund.reset_index().sort_values("DT_COMPTC")
            cota_by_fund.columns = ["DT_COMPTC"] + [f"Cota - {c}" for c in cota_by_fund.columns[1:]]
            cons_per_class["cota_por_classe"] = cota_by_fund

    # Rentabilidade by fund
    if "RENTAB_MES" in combined.columns:
        rentab_by_fund = combined.pivot_table(
            index="DT_COMPTC", columns="_fund_name", values="RENTAB_MES", aggfunc="mean",
        )
        if not rentab_by_fund.empty:
            rentab_by_fund = rentab_by_fund.reset_index().sort_values("DT_COMPTC")
            rentab_by_fund.columns = ["DT_COMPTC"] + [f"Rentab - {c}" for c in rentab_by_fund.columns[1:]]
            cons_per_class["rentab_por_fundo"] = rentab_by_fund

    # Cotistas by fund
    if "NR_COTISTAS" in combined.columns:
        cotistas_by_fund = combined.pivot_table(
            index="DT_COMPTC", columns="_fund_name", values="NR_COTISTAS", aggfunc="sum",
        )
        if not cotistas_by_fund.empty:
            cotistas_by_fund = cotistas_by_fund.reset_index().sort_values("DT_COMPTC")
            cotistas_by_fund.columns = ["DT_COMPTC"] + [f"Cotistas - {c}" for c in cotistas_by_fund.columns[1:]]
            cons_per_class["cotistas_por_classe"] = cotistas_by_fund

    return consolidated, all_tables, cons_per_class, cdi_df_out


# ── Sidebar ──────────────────────────────────────────────────────────────────

CONSOLIDATED_LABEL = "Facio Consolidado"

with st.sidebar:
    st.markdown("### Facio FIDC Monitor")
    st.markdown("---")

    fund_options = [CONSOLIDATED_LABEL] + [f["name"] for f in FUNDS]
    selected_fund_name = st.selectbox("Fundo", fund_options)
    is_consolidated = selected_fund_name == CONSOLIDATED_LABEL

    if is_consolidated:
        selected_fund = None
        fund_name = CONSOLIDATED_LABEL
        st.markdown("**Visao consolidada de todos os fundos Facio**")
        operational = [f for f in FUNDS if f["status"] == "Operacional"]
        for f in FUNDS:
            status_color = "#22c55e" if f["status"] == "Operacional" else "#f59e0b"
            st.markdown(
                f"<small>{f['name']}: <span style='color:{status_color}'>{f['status']}</span></small>",
                unsafe_allow_html=True,
            )
    else:
        selected_fund = next(f for f in FUNDS if f["name"] == selected_fund_name)
        fund_name = selected_fund["name"]
        st.markdown(f"**CNPJ:** {selected_fund['cnpj']}")
        if selected_fund.get("status"):
            status_color = "#22c55e" if selected_fund["status"] == "Operacional" else "#f59e0b"
            st.markdown(f"**Status:** <span style='color:{status_color}'>{selected_fund['status']}</span>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("##### Periodo de Analise")

    today = date.today()
    if is_consolidated:
        fund_start = min(date.fromisoformat(f["start_date"]) for f in FUNDS)
    else:
        fund_start = date.fromisoformat(selected_fund["start_date"])

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        start_month = st.date_input(
            "De",
            value=fund_start,
            min_value=fund_start,
            max_value=today,
            format="YYYY-MM-DD",
        )
    with col_s2:
        end_month = st.date_input(
            "Ate",
            value=today,
            min_value=fund_start,
            max_value=today,
            format="YYYY-MM-DD",
        )

    # Validate date range
    if start_month < fund_start:
        st.warning(f"Inicio ajustado: fundo comecou em {fund_start.strftime('%m/%Y')}")
        start_month = fund_start
    if start_month > end_month:
        st.error("Data inicial deve ser anterior a data final.")

    refresh = st.button("Atualizar Dados", type="primary", width="stretch")

    # Configurable alert thresholds
    st.markdown("---")
    st.markdown("##### Limiares de Alerta")
    with st.expander("Configurar", expanded=False):
        thresh_inad_danger = st.number_input(
            "Inadimplencia critica (%)", value=15.0, step=1.0, key="thresh_inad_d",
        )
        thresh_inad_warning = st.number_input(
            "Inadimplencia alerta (%)", value=10.0, step=1.0, key="thresh_inad_w",
        )
        thresh_pl_danger = st.number_input(
            "Queda PL critica (%)", value=10.0, step=1.0, key="thresh_pl_d",
        )
        thresh_sub_danger = st.number_input(
            "Subordinacao minima critica (%)", value=10.0, step=1.0, key="thresh_sub_d",
        )
        thresh_sub_warning = st.number_input(
            "Subordinacao minima alerta (%)", value=20.0, step=1.0, key="thresh_sub_w",
        )

    st.markdown("---")
    st.markdown(
        "<small style='color:#94a3b8'>Dados: CVM Portal de Dados Abertos<br>"
        "Informes Mensais de FIDC</small>",
        unsafe_allow_html=True,
    )


# ── Load data ────────────────────────────────────────────────────────────────

start_str = start_month.strftime("%Y-%m")
end_str = end_month.strftime("%Y-%m")

# Determine if this is a force refresh (user clicked "Atualizar Dados")
force_refresh = refresh

if force_refresh:
    # Incremental refresh: only clear the last 2 months of raw data (may have updates)
    # and clear all processed caches so they get re-built
    from datetime import datetime
    end_parts = end_str.split("-")
    end_y, end_m = int(end_parts[0]), int(end_parts[1])
    months_to_redownload = [(end_y, end_m)]
    # Also re-download previous month (CVM may publish corrections)
    prev_m = end_m - 1 if end_m > 1 else 12
    prev_y = end_y if end_m > 1 else end_y - 1
    months_to_redownload.append((prev_y, prev_m))
    clear_raw_months(months_to_redownload)
    clear_cache()

spinner_msg = "Atualizando dados do CVM..." if force_refresh else "Carregando dados..."
with st.spinner(spinner_msg):
    if is_consolidated:
        kpi_df, tables, per_class, cdi_df = load_consolidated_data(start_str, end_str, force_refresh=force_refresh)
    else:
        kpi_df, tables, per_class, cdi_df = load_data(start_str, end_str, selected_fund["cnpj_raw"], fund_name, force_refresh=force_refresh)

if kpi_df is None or kpi_df.empty:
    st.error("Nenhum dado disponivel. Verifique a conexao e o periodo selecionado.")
    st.stop()

# ── Compute all analytics ───────────────────────────────────────────────────

per_class = per_class or {}
credit_quality = compute_credit_quality_metrics(kpi_df)
flow_metrics = compute_flow_metrics(kpi_df)
perf_metrics = compute_performance_metrics(kpi_df, per_class)
sub_ratios = compute_subordination_ratios(per_class)
spread_metrics = compute_cdi_spread(perf_metrics, cdi_df)
pl_waterfall = compute_pl_waterfall(kpi_df)
data_quality = compute_data_quality(kpi_df, tables)

# Pass custom thresholds to alert function
alerts = get_alert_flags(
    kpi_df, per_class,
    thresholds={
        "inad_danger": thresh_inad_danger,
        "inad_warning": thresh_inad_warning,
        "pl_danger": thresh_pl_danger,
        "sub_danger": thresh_sub_danger,
        "sub_warning": thresh_sub_warning,
    },
)

latest = kpi_df.iloc[-1]
prev = kpi_df.iloc[-2] if len(kpi_df) > 1 else None

latest_date = kpi_df["DT_COMPTC"].max()
date_label = latest_date.strftime("%b/%Y") if pd.notna(latest_date) else "N/A"

# CDI fetch warning
cdi_ok = cdi_df is not None and not cdi_df.empty and "CDI_%" in cdi_df.columns
if not cdi_ok:
    st.warning("Dados do CDI indisponiveis (API BCB falhou). Graficos de benchmark CDI estarao incompletos.")

# ── Header ───────────────────────────────────────────────────────────────────

st.markdown(f"## {fund_name}")

# Data quality indicator inline
dq_pct = data_quality["completeness_pct"]
dq_color = "#22c55e" if dq_pct >= 80 else "#f59e0b" if dq_pct >= 50 else "#ef4444"
dq_label = f"<span style='color:{dq_color};font-weight:600'>{dq_pct:.0f}%</span>"
st.markdown(
    f"Dados ate **{date_label}** · {len(kpi_df)} meses de historico · "
    f"Qualidade dos dados: {dq_label}",
    unsafe_allow_html=True,
)
if data_quality["missing_kpis"]:
    st.caption(f"KPIs indisponiveis: {', '.join(data_quality['missing_kpis'])}")
if data_quality.get("date_gaps"):
    for gap in data_quality["date_gaps"]:
        st.caption(f"Gap de dados: {gap}")
if data_quality.get("anomalies"):
    for anomaly in data_quality["anomalies"]:
        st.warning(f"Anomalia detectada: {anomaly}")

# ── Alerts ───────────────────────────────────────────────────────────────────

for alert in alerts:
    icon = {"danger": "🔴", "warning": "🟡", "info": "🟢"}[alert["level"]]
    st.markdown(
        f'<div class="alert-{alert["level"]}">{icon} {alert["message"]}</div>',
        unsafe_allow_html=True,
    )

st.markdown("")

# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_overview, tab_credit, tab_subordination, tab_performance, tab_compare, tab_flow, tab_data = st.tabs([
    "Visao Geral",
    "Qualidade de Credito",
    "Subordinacao",
    "Performance",
    "Comparacao Fundos",
    "Fluxo da Carteira",
    "Dados Brutos",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════

with tab_overview:
    def _delta(col):
        if prev is None or col not in kpi_df.columns:
            return None
        v, p = latest.get(col), prev.get(col)
        if pd.notna(v) and pd.notna(p) and p != 0:
            return f"{(v - p) / p * 100:+.2f}%"
        return None

    # Row 1: Key metrics
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Patrimonio Liquido", format_brl(latest.get("PL")), _delta("PL"))
    with c2:
        st.metric("Ativo Total", format_brl(latest.get("ATIVO_TOTAL")), _delta("ATIVO_TOTAL"))
    with c3:
        val = latest.get("TAXA_INADIMPLENCIA")
        delta_inad = None
        if prev is not None and "TAXA_INADIMPLENCIA" in kpi_df.columns:
            prev_val = prev.get("TAXA_INADIMPLENCIA")
            if pd.notna(val) and pd.notna(prev_val):
                delta_inad = f"{val - prev_val:+.2f}pp"
        st.metric("Taxa Inadimplencia", format_pct(val), delta_inad, delta_color="inverse")
    with c4:
        st.metric("Valor da Cota", format_brl(latest.get("VALOR_COTA")), _delta("VALOR_COTA"))

    # Row 2: Secondary metrics
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        nr = latest.get("NR_COTISTAS")
        st.metric("Cotistas", f"{int(nr)}" if pd.notna(nr) else "—", _delta("NR_COTISTAS"))
    with c6:
        rentab = latest.get("RENTAB_MES")
        st.metric("Rentabilidade Mensal", format_pct(rentab), None)
    with c7:
        # Subordination index
        sub_val = None
        sub_delta = None
        if sub_ratios is not None and "Subordinacao_Senior_%" in sub_ratios.columns and len(sub_ratios) > 0:
            sub_val = sub_ratios.iloc[-1].get("Subordinacao_Senior_%")
            if len(sub_ratios) > 1:
                sub_prev = sub_ratios.iloc[-2].get("Subordinacao_Senior_%")
                if pd.notna(sub_val) and pd.notna(sub_prev):
                    sub_delta = f"{sub_val - sub_prev:+.2f}pp"
        st.metric("Subordinacao Senior", format_pct(sub_val), sub_delta)
    with c8:
        st.metric("Aquisicoes", format_brl(latest.get("AQUISICOES")), _delta("AQUISICOES"))

    st.markdown("")

    # Row 3: Charts
    col_left, col_right = st.columns(2)

    with col_left:
        pl_df = per_class.get("pl_por_classe")
        if pl_df is not None and not pl_df.empty:
            pl_cols = [c for c in pl_df.columns if c != "DT_COMPTC"]
            if is_consolidated:
                fig = styled_area_chart(
                    pl_df, "DT_COMPTC", pl_cols,
                    "Patrimonio Liquido por Fundo", y_format="brl",
                    colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
                )
            else:
                fig = styled_line_chart(
                    pl_df, "DT_COMPTC", pl_cols,
                    "Patrimonio Liquido por Classe", y_format="brl",
                    colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
                )
            st.plotly_chart(fig, width="stretch", key="overview_pl")
        elif "PL" in perf_metrics.columns:
            fig = styled_line_chart(
                perf_metrics, "DT_COMPTC", ["PL"],
                "Patrimonio Liquido", y_format="brl",
            )
            st.plotly_chart(fig, width="stretch", key="overview_pl")

    with col_right:
        if "Taxa_Inadimplencia_%" in credit_quality.columns and credit_quality["Taxa_Inadimplencia_%"].notna().any():
            fig = styled_line_chart(
                credit_quality, "DT_COMPTC", ["Taxa_Inadimplencia_%"],
                "Taxa de Inadimplencia", y_format="pct",
                colors=[COLORS["danger"]],
            )
            st.plotly_chart(fig, width="stretch", key="overview_inadimplencia")
        else:
            st.info("Dados de inadimplencia nao disponiveis para este periodo.")

    # Subordination + Quota in second row
    col_left2, col_right2 = st.columns(2)

    with col_left2:
        if sub_ratios is not None and "Subordinacao_Senior_%" in sub_ratios.columns:
            sub_cols = [c for c in sub_ratios.columns if c.endswith("_%") and "Subordinacao" in c]
            if sub_cols:
                fig = styled_line_chart(
                    sub_ratios, "DT_COMPTC", sub_cols,
                    "Razao de Subordinacao", y_format="pct",
                    colors=[COLORS["primary"], COLORS["warning"]],
                )
                st.plotly_chart(fig, width="stretch", key="overview_subordinacao")

    with col_right2:
        cota_df = per_class.get("cota_por_classe")
        if cota_df is not None and not cota_df.empty:
            cota_cols = [c for c in cota_df.columns if c != "DT_COMPTC"]
            fig = styled_line_chart(
                cota_df, "DT_COMPTC", cota_cols,
                "Valor da Cota por Classe", y_format="brl",
                colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
            )
            st.plotly_chart(fig, width="stretch", key="overview_cota")

    # Row 5: PL Waterfall chart
    if pl_waterfall is not None and not pl_waterfall.empty:
        st.markdown("")
        # Show last 12 months max for readability
        wf = pl_waterfall.tail(12).copy()
        wf["date_label"] = pd.to_datetime(wf["DT_COMPTC"]).dt.strftime("%b/%Y")

        fig = go.Figure()
        components = [
            ("Rendimentos", COLORS["success"]),
            ("Aquisicoes", COLORS["primary"]),
            ("Resgates", COLORS["danger"]),
            ("Inadimplencia", COLORS["warning"]),
            ("Outros", COLORS["muted"]),
        ]
        for comp_name, color in components:
            if comp_name in wf.columns and wf[comp_name].notna().any():
                fig.add_trace(go.Bar(
                    x=wf["date_label"], y=wf[comp_name],
                    name=comp_name, marker_color=color, opacity=0.85,
                ))
        # Add net PL change as a line
        fig.add_trace(go.Scatter(
            x=wf["date_label"], y=wf["Variacao_PL"],
            name="Variacao PL", mode="lines+markers",
            line=dict(color="#1e293b", width=2.5),
            marker=dict(size=6),
        ))
        fig.update_layout(
            **CHART_LAYOUT,
            title="Decomposicao da Variacao do PL",
            barmode="relative",
        )
        fig.update_yaxes(tickformat=",.0f", tickprefix="R$ ")
        st.plotly_chart(fig, width="stretch", key="overview_waterfall")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: CREDIT QUALITY
# ═══════════════════════════════════════════════════════════════════════════════

with tab_credit:
    st.markdown('<div class="section-header">Qualidade da Carteira de Credito</div>', unsafe_allow_html=True)

    # Summary metrics
    cc1, cc2, cc3, cc4 = st.columns(4)
    cq_latest = credit_quality.iloc[-1] if not credit_quality.empty else {}

    with cc1:
        st.metric("Carteira Total", format_brl(cq_latest.get("Carteira_Total")))
    with cc2:
        st.metric("Performar", format_brl(cq_latest.get("DC_Performar")))
    with cc3:
        st.metric("Nao Performar", format_brl(cq_latest.get("DC_Nao_Performar")))
    with cc4:
        st.metric("Cobertura de Provisao", format_pct(cq_latest.get("Cobertura_Provisao_%")))

    st.markdown("")

    col1, col2 = st.columns(2)

    with col1:
        # Default rate evolution
        if "Taxa_Inadimplencia_%" in credit_quality.columns and credit_quality["Taxa_Inadimplencia_%"].notna().any():
            fig = styled_line_chart(
                credit_quality, "DT_COMPTC", ["Taxa_Inadimplencia_%"],
                "Evolucao da Taxa de Inadimplencia", y_format="pct",
                colors=[COLORS["danger"]],
            )
            st.plotly_chart(fig, width="stretch", key="credit_inadimplencia")
        else:
            st.info("Dados de inadimplencia nao disponiveis para este periodo.")

    with col2:
        # Performing vs Non-performing
        dc_cols = [c for c in ["DC_Performar", "DC_Nao_Performar"] if c in credit_quality.columns]
        if dc_cols:
            fig = styled_bar_chart(
                credit_quality, "DT_COMPTC", dc_cols,
                "Carteira: Performar vs Nao Performar", y_format="brl",
                colors=[COLORS["success"], COLORS["danger"]],
                barmode="stack",
            )
            st.plotly_chart(fig, width="stretch", key="credit_performar")

    col3, col4 = st.columns(2)

    with col3:
        # Provisioning coverage
        if "Cobertura_Provisao_%" in credit_quality.columns:
            fig = styled_line_chart(
                credit_quality, "DT_COMPTC", ["Cobertura_Provisao_%"],
                "Cobertura de Provisao (%)", y_format="pct",
                colors=[COLORS["info"]],
            )
            st.plotly_chart(fig, width="stretch", key="credit_cobertura")

    with col4:
        # MoM change in default rate
        if "Inadimplencia_MoM_pp" in credit_quality.columns:
            fig = styled_bar_chart(
                credit_quality, "DT_COMPTC", ["Inadimplencia_MoM_pp"],
                "Variacao Mensal Inadimplencia (pp)", y_format="pct",
                colors=[COLORS["warning"]],
            )
            st.plotly_chart(fig, width="stretch", key="credit_mom")

    # Data table
    with st.expander("Dados detalhados - Qualidade de Credito"):
        display_cq = credit_quality.copy()
        display_cq["DT_COMPTC"] = display_cq["DT_COMPTC"].dt.strftime("%Y-%m")
        st.dataframe(display_cq, width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: SUBORDINATION
# ═══════════════════════════════════════════════════════════════════════════════

with tab_subordination:
    st.markdown('<div class="section-header">Analise de Subordinacao (Credit Enhancement)</div>', unsafe_allow_html=True)

    if sub_ratios is not None and not sub_ratios.empty:
        sub_latest = sub_ratios.iloc[-1]
        sub_prev = sub_ratios.iloc[-2] if len(sub_ratios) > 1 else None

        def _sub_delta(col):
            if sub_prev is None:
                return None
            v, p = sub_latest.get(col), sub_prev.get(col)
            if pd.notna(v) and pd.notna(p):
                diff = v - p
                return f"{diff:+.2f}pp"
            return None

        # Summary cards with MoM deltas
        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1:
            pl_delta = None
            if sub_prev is not None:
                pl_v, pl_p = sub_latest.get("PL_Total"), sub_prev.get("PL_Total")
                if pd.notna(pl_v) and pd.notna(pl_p) and pl_p != 0:
                    pl_delta = f"{(pl_v - pl_p) / pl_p * 100:+.2f}%"
            st.metric("PL Total", format_brl(sub_latest.get("PL_Total")), pl_delta)
        with sc2:
            st.metric(
                "Subordinacao Senior",
                format_pct(sub_latest.get("Subordinacao_Senior_%")),
                _sub_delta("Subordinacao_Senior_%"),
            )
        with sc3:
            st.metric(
                "Subordinacao Mezanino",
                format_pct(sub_latest.get("Subordinacao_Mezanino_%")),
                _sub_delta("Subordinacao_Mezanino_%"),
            )
        with sc4:
            st.metric(
                "Senior Share",
                format_pct(sub_latest.get("Senior_%")),
                _sub_delta("Senior_%"),
            )

        st.markdown("")

        # Class filter for PL composition chart
        pl_cols = [c for c in sub_ratios.columns if c.startswith("PL_") and not c.endswith("%") and c != "PL_Total"]
        if pl_cols:
            sub_class_filter = st.multiselect(
                "Filtrar classes:", pl_cols, default=pl_cols,
                key="sub_class_filter",
            )
        else:
            sub_class_filter = []

        col1, col2 = st.columns(2)

        with col1:
            # Subordination ratio evolution
            sub_cols = [c for c in sub_ratios.columns if "Subordinacao" in c and c.endswith("%")]
            if sub_cols:
                fig = styled_line_chart(
                    sub_ratios, "DT_COMPTC", sub_cols,
                    "Evolucao da Razao de Subordinacao", y_format="pct",
                    colors=[COLORS["primary"], COLORS["warning"]],
                )
                st.plotly_chart(fig, width="stretch", key="sub_ratio")

        with col2:
            # PL composition over time (stacked area)
            if sub_class_filter:
                fig = styled_area_chart(
                    sub_ratios, "DT_COMPTC", sub_class_filter,
                    "Composicao do PL por Classe", y_format="brl",
                    colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
                )
                st.plotly_chart(fig, width="stretch", key="sub_pl_classe")

        # PL share pie chart (latest month)
        share_cols = [c for c in sub_ratios.columns if c.endswith("_%") and "Subordinacao" not in c]
        if share_cols:
            col_pie, col_table = st.columns([1, 2])
            with col_pie:
                labels = [c.replace("_%", "") for c in share_cols]
                values = [sub_latest.get(c, 0) for c in share_cols]
                fig = go.Figure(data=[go.Pie(
                    labels=labels, values=values,
                    hole=0.4,
                    marker_colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
                    textinfo="label+percent",
                    textfont_size=13,
                )])
                fig.update_layout(
                    **{k: v for k, v in CHART_LAYOUT.items() if k != "hovermode"},
                    title=f"Composicao PL — {date_label}",
                    showlegend=False,
                )
                st.plotly_chart(fig, width="stretch", key="sub_pie")

            with col_table:
                with st.expander("Dados detalhados - Subordinacao", expanded=True):
                    display_sub = sub_ratios.copy()
                    display_sub["DT_COMPTC"] = display_sub["DT_COMPTC"].dt.strftime("%Y-%m")
                    st.dataframe(display_sub, width="stretch", hide_index=True)
    else:
        st.info("Dados de subordinacao por classe nao disponiveis para o periodo selecionado.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════════════

with tab_performance:
    st.markdown('<div class="section-header">Performance do Fundo</div>', unsafe_allow_html=True)

    perf_latest = perf_metrics.iloc[-1] if not perf_metrics.empty else {}
    spread_latest = spread_metrics.iloc[-1] if not spread_metrics.empty else {}

    # Summary cards — Row 1: core metrics
    pc1, pc2, pc3, pc4 = st.columns(4)
    with pc1:
        st.metric("PL", format_brl(perf_latest.get("PL")))
    with pc2:
        st.metric("Rentabilidade Mensal", format_pct(perf_latest.get("Rentabilidade_%")))
    with pc3:
        spread_val = spread_latest.get("Spread_bps")
        spread_label = f"{spread_val:+.0f} bps" if pd.notna(spread_val) else "—"
        st.metric("Spread vs CDI", spread_label)
    with pc4:
        st.metric("Valor da Cota", format_brl(perf_latest.get("Valor_Cota")))

    # Row 2: cumulative returns
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1:
        st.metric("Retorno YTD", format_pct(spread_latest.get("Retorno_YTD_%")))
    with rc2:
        st.metric("Retorno 3M", format_pct(spread_latest.get("Retorno_3M_%")))
    with rc3:
        st.metric("Retorno 6M", format_pct(spread_latest.get("Retorno_6M_%")))
    with rc4:
        st.metric("Retorno 12M", format_pct(spread_latest.get("Retorno_12M_%")))

    st.markdown("")

    col1, col2 = st.columns(2)

    with col1:
        # Cumulative return: Fund vs CDI
        if not spread_metrics.empty and "Acumulado_Fundo_%" in spread_metrics.columns:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=spread_metrics["DT_COMPTC"], y=spread_metrics["Acumulado_Fundo_%"],
                name="Fundo (acum.)", mode="lines+markers",
                line=dict(color=COLORS["success"], width=2.5),
                marker=dict(size=5),
            ))
            if "Acumulado_CDI_%" in spread_metrics.columns:
                fig.add_trace(go.Scatter(
                    x=spread_metrics["DT_COMPTC"], y=spread_metrics["Acumulado_CDI_%"],
                    name="CDI (acum.)", mode="lines+markers",
                    line=dict(color=COLORS["warning"], width=2.5, dash="dot"),
                    marker=dict(size=5),
                ))
            fig.update_layout(**CHART_LAYOUT, title="Retorno Acumulado: Fundo vs CDI")
            fig.update_yaxes(ticksuffix="%")
            fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
            st.plotly_chart(fig, width="stretch", key="perf_acumulado")

    with col2:
        # Monthly spread (bps)
        if not spread_metrics.empty and "Spread_bps" in spread_metrics.columns:
            sm = spread_metrics.copy()
            sm["Color"] = sm["Spread_bps"].apply(
                lambda x: COLORS["success"] if pd.notna(x) and x >= 0 else COLORS["danger"]
            )
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=sm["DT_COMPTC"], y=sm["Spread_bps"],
                marker_color=sm["Color"], name="Spread (bps)",
            ))
            fig.update_layout(**CHART_LAYOUT, title="Spread Mensal vs CDI (bps)")
            fig.update_yaxes(ticksuffix=" bps")
            fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
            st.plotly_chart(fig, width="stretch", key="perf_spread")

    col3, col4 = st.columns(2)

    with col3:
        # Rentabilidade vs CDI benchmark (monthly)
        # For consolidated view, show per-fund breakdown
        rentab_per_fund = per_class.get("rentab_por_fundo") if is_consolidated else None
        if rentab_per_fund is not None and not rentab_per_fund.empty:
            rentab_cols = [c for c in rentab_per_fund.columns if c != "DT_COMPTC"]
            fig = styled_line_chart(
                rentab_per_fund, "DT_COMPTC", rentab_cols,
                "Rentabilidade Mensal (%)", y_format="pct",
            )
            if cdi_ok and not spread_metrics.empty and "CDI_%" in spread_metrics.columns:
                fig.add_trace(go.Scatter(
                    x=spread_metrics["DT_COMPTC"], y=spread_metrics["CDI_%"],
                    name="CDI", mode="lines+markers",
                    line=dict(color=COLORS["muted"], width=2, dash="dot"),
                    marker=dict(size=4),
                ))
            st.plotly_chart(fig, width="stretch", key="perf_rentab")
        elif "Rentabilidade_%" in perf_metrics.columns:
            fig = go.Figure()
            # Filter out NaN rentabilidade
            rentab_data = perf_metrics.dropna(subset=["Rentabilidade_%"])
            fig.add_trace(go.Bar(
                x=rentab_data["DT_COMPTC"], y=rentab_data["Rentabilidade_%"],
                name="Fundo", marker_color=COLORS["success"], opacity=0.9,
            ))
            if cdi_ok and not spread_metrics.empty and "CDI_%" in spread_metrics.columns:
                fig.add_trace(go.Scatter(
                    x=spread_metrics["DT_COMPTC"], y=spread_metrics["CDI_%"],
                    name="CDI", mode="lines+markers",
                    line=dict(color=COLORS["warning"], width=2.5, dash="dot"),
                    marker=dict(size=5),
                ))
            fig.update_layout(**CHART_LAYOUT, title="Rentabilidade Mensal vs CDI")
            fig.update_yaxes(ticksuffix="%")
            fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
            st.plotly_chart(fig, width="stretch", key="perf_rentab")

    with col4:
        pl_df = per_class.get("pl_por_classe")
        if pl_df is not None and not pl_df.empty:
            pl_cols = [c for c in pl_df.columns if c != "DT_COMPTC"]
            if is_consolidated:
                fig = styled_area_chart(
                    pl_df, "DT_COMPTC", pl_cols,
                    "PL por Fundo", y_format="brl",
                    colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
                )
            else:
                fig = styled_line_chart(
                    pl_df, "DT_COMPTC", pl_cols,
                    "PL por Classe", y_format="brl",
                    colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
                )
            st.plotly_chart(fig, width="stretch", key="perf_pl")
        elif "PL" in perf_metrics.columns:
            fig = styled_area_chart(
                perf_metrics, "DT_COMPTC", ["PL"],
                "Evolucao do Patrimonio Liquido", y_format="brl",
                colors=[COLORS["primary"]],
            )
            st.plotly_chart(fig, width="stretch", key="perf_pl")

    col5, col6 = st.columns(2)

    with col5:
        # Quota value evolution per class
        cota_df = per_class.get("cota_por_classe")
        if cota_df is not None and not cota_df.empty:
            cota_cols = [c for c in cota_df.columns if c != "DT_COMPTC"]
            perf_class_filter = st.multiselect(
                "Filtrar classes:", cota_cols, default=cota_cols,
                key="perf_class_filter",
            )
            if perf_class_filter:
                fig = styled_line_chart(
                    cota_df, "DT_COMPTC", perf_class_filter,
                    "Valor da Cota por Classe", y_format="brl",
                    colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
                )
                st.plotly_chart(fig, width="stretch", key="perf_cota")

    with col6:
        if "Nr_Cotistas" in perf_metrics.columns:
            # Use per-class cotistas data if available (more complete)
            cotistas_df = per_class.get("cotistas_por_classe")
            if cotistas_df is not None and not cotistas_df.empty:
                cotistas_cols = [c for c in cotistas_df.columns if c != "DT_COMPTC"]
                # Sum across classes for total cotistas
                total_cotistas = cotistas_df.copy()
                total_cotistas["Total Cotistas"] = total_cotistas[cotistas_cols].sum(axis=1)
                fig = styled_line_chart(
                    total_cotistas, "DT_COMPTC", ["Total Cotistas"],
                    "Numero de Cotistas", colors=[COLORS["info"]],
                )
            else:
                fig = styled_line_chart(
                    perf_metrics, "DT_COMPTC", ["Nr_Cotistas"],
                    "Numero de Cotistas", colors=[COLORS["info"]],
                )
            st.plotly_chart(fig, width="stretch", key="perf_cotistas")

    # Row 4: Subordination and Default Rate
    col7, col8 = st.columns(2)

    with col7:
        if sub_ratios is not None and "Subordinacao_Senior_%" in sub_ratios.columns:
            sub_cols = [c for c in sub_ratios.columns if c.endswith("_%") and "Subordinacao" in c]
            if sub_cols:
                fig = styled_line_chart(
                    sub_ratios, "DT_COMPTC", sub_cols,
                    "Indice de Subordinacao", y_format="pct",
                    colors=[COLORS["primary"], COLORS["warning"]],
                )
                st.plotly_chart(fig, width="stretch", key="perf_subordinacao")
        else:
            st.info("Indice de subordinacao: dados por classe nao disponiveis.")

    with col8:
        if "Taxa_Inadimplencia_%" in credit_quality.columns and credit_quality["Taxa_Inadimplencia_%"].notna().any():
            fig = styled_line_chart(
                credit_quality, "DT_COMPTC", ["Taxa_Inadimplencia_%"],
                "Taxa de Inadimplencia", y_format="pct",
                colors=[COLORS["danger"]],
            )
            st.plotly_chart(fig, width="stretch", key="perf_inadimplencia")
        else:
            st.info("Dados de inadimplencia nao disponiveis para este periodo.")

    with st.expander("Dados detalhados - Performance & Spread"):
        if not spread_metrics.empty:
            display_spread = spread_metrics.copy()
            display_spread["DT_COMPTC"] = display_spread["DT_COMPTC"].dt.strftime("%Y-%m")
            st.dataframe(display_spread, width="stretch", hide_index=True)
        else:
            display_perf = perf_metrics.copy()
            display_perf["DT_COMPTC"] = display_perf["DT_COMPTC"].dt.strftime("%Y-%m")
            st.dataframe(display_perf, width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5: FUND COMPARISON
# ═══════════════════════════════════════════════════════════════════════════════

with tab_compare:
    st.markdown('<div class="section-header">Comparacao entre Fundos Facio</div>', unsafe_allow_html=True)

    # Load data for all funds in parallel
    compare_funds = [f for f in FUNDS if f["name"] != fund_name and f["status"] == "Operacional"]

    if not compare_funds:
        st.info("Nenhum outro fundo operacional para comparar.")
    else:
        st.markdown("Comparando com o fundo selecionado na sidebar.")

        @st.cache_data(ttl=3600, show_spinner=False)
        def load_comparison_data(fund_cnpj_raw: str, s_str: str, e_str: str, comp_fund_name: str = ""):
            """Load KPIs for a comparison fund."""
            from datetime import date as d
            s_parts = s_str.split("-")
            e_parts = e_str.split("-")
            s_date = d(int(s_parts[0]), int(s_parts[1]), 1)
            e_date = d(int(e_parts[0]), int(e_parts[1]), 1)
            data_dirs = download_monthly_zips(s_date, e_date)
            if not data_dirs:
                return None
            fund_names_hint = [comp_fund_name] if comp_fund_name else None
            t = parse_all_tables(data_dirs, [fund_cnpj_raw], fund_names=fund_names_hint)
            if not t:
                return None
            kdf = extract_kpis(t)
            if kdf.empty:
                return None
            return compute_trends(kdf)

        all_fund_kpis = {fund_name: kpi_df}
        with st.spinner("Carregando dados dos outros fundos..."):
            for cf in compare_funds:
                cf_start = max(start_str, cf["start_date"][:7])
                cf_kpi = load_comparison_data(cf["cnpj_raw"], cf_start, end_str, cf["name"])
                if cf_kpi is not None and not cf_kpi.empty:
                    all_fund_kpis[cf["name"]] = cf_kpi

        if len(all_fund_kpis) < 2:
            st.warning("Dados insuficientes para comparacao no periodo selecionado.")
        else:
            # Comparison metrics table
            comp_rows = []
            for fname, fkpi in all_fund_kpis.items():
                fl = fkpi.iloc[-1]
                comp_rows.append({
                    "Fundo": fname,
                    "PL": format_brl(fl.get("PL")),
                    "Inadimplencia (%)": format_pct(fl.get("TAXA_INADIMPLENCIA")),
                    "Rentab. Mensal (%)": format_pct(fl.get("RENTAB_MES")),
                    "Valor Cota": format_brl(fl.get("VALOR_COTA")),
                    "Cotistas": int(fl.get("NR_COTISTAS")) if pd.notna(fl.get("NR_COTISTAS")) else "—",
                })
            st.dataframe(pd.DataFrame(comp_rows), width="stretch", hide_index=True)

            st.markdown("")

            # Comparison charts
            comp_col1, comp_col2 = st.columns(2)

            with comp_col1:
                # PL comparison
                fig = go.Figure()
                palette = [COLORS["primary"], COLORS["success"], COLORS["warning"], COLORS["danger"]]
                for i, (fname, fkpi) in enumerate(all_fund_kpis.items()):
                    if "PL" in fkpi.columns:
                        fig.add_trace(go.Scatter(
                            x=fkpi["DT_COMPTC"], y=fkpi["PL"],
                            name=fname, mode="lines+markers",
                            line=dict(color=palette[i % len(palette)], width=2.5),
                            marker=dict(size=5),
                        ))
                fig.update_layout(**CHART_LAYOUT, title="Patrimonio Liquido")
                fig.update_yaxes(tickformat=",.0f", tickprefix="R$ ")
                fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
                st.plotly_chart(fig, width="stretch", key="comp_pl")

            with comp_col2:
                # Default rate comparison
                fig = go.Figure()
                for i, (fname, fkpi) in enumerate(all_fund_kpis.items()):
                    if "TAXA_INADIMPLENCIA" in fkpi.columns:
                        fig.add_trace(go.Scatter(
                            x=fkpi["DT_COMPTC"], y=fkpi["TAXA_INADIMPLENCIA"],
                            name=fname, mode="lines+markers",
                            line=dict(color=palette[i % len(palette)], width=2.5),
                            marker=dict(size=5),
                        ))
                fig.update_layout(**CHART_LAYOUT, title="Taxa de Inadimplencia")
                fig.update_yaxes(ticksuffix="%")
                fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
                st.plotly_chart(fig, width="stretch", key="comp_inadimplencia")

            comp_col3, comp_col4 = st.columns(2)

            with comp_col3:
                # Rentabilidade comparison
                fig = go.Figure()
                for i, (fname, fkpi) in enumerate(all_fund_kpis.items()):
                    if "RENTAB_MES" in fkpi.columns:
                        fig.add_trace(go.Scatter(
                            x=fkpi["DT_COMPTC"], y=fkpi["RENTAB_MES"],
                            name=fname, mode="lines+markers",
                            line=dict(color=palette[i % len(palette)], width=2.5),
                            marker=dict(size=5),
                        ))
                fig.update_layout(**CHART_LAYOUT, title="Rentabilidade Mensal (%)")
                fig.update_yaxes(ticksuffix="%")
                fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
                st.plotly_chart(fig, width="stretch", key="comp_rentab")

            with comp_col4:
                # Quota value comparison
                fig = go.Figure()
                for i, (fname, fkpi) in enumerate(all_fund_kpis.items()):
                    if "VALOR_COTA" in fkpi.columns:
                        fig.add_trace(go.Scatter(
                            x=fkpi["DT_COMPTC"], y=fkpi["VALOR_COTA"],
                            name=fname, mode="lines+markers",
                            line=dict(color=palette[i % len(palette)], width=2.5),
                            marker=dict(size=5),
                        ))
                fig.update_layout(**CHART_LAYOUT, title="Valor da Cota")
                fig.update_yaxes(tickformat=",.2f", tickprefix="R$ ")
                fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
                st.plotly_chart(fig, width="stretch", key="comp_cota")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6: PORTFOLIO FLOW
# ═══════════════════════════════════════════════════════════════════════════════

with tab_flow:
    st.markdown('<div class="section-header">Fluxo da Carteira</div>', unsafe_allow_html=True)

    flow_latest = flow_metrics.iloc[-1] if not flow_metrics.empty else {}

    # Check if flow data exists
    has_flow = any(
        c in flow_metrics.columns
        for c in ["Aquisicoes", "Resgates", "Substituicoes", "Fluxo_Liquido"]
    )
    if not has_flow:
        st.warning(
            "Dados de fluxo indisponiveis para este fundo. "
            "Os KPIs AQUISICOES, RESGATES e SUBSTITUICAO nao foram encontrados nos dados CVM. "
            "Verifique a aba 'Dados Brutos' para inspecionar as colunas disponiveis."
        )

    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        st.metric("Aquisicoes", format_brl(flow_latest.get("Aquisicoes")))
    with fc2:
        st.metric("Resgates", format_brl(flow_latest.get("Resgates")))
    with fc3:
        st.metric("Substituicoes", format_brl(flow_latest.get("Substituicoes")))
    with fc4:
        st.metric("Fluxo Liquido", format_brl(flow_latest.get("Fluxo_Liquido")))

    st.markdown("")

    col1, col2 = st.columns(2)

    with col1:
        flow_bar_cols = [c for c in ["Aquisicoes", "Resgates"] if c in flow_metrics.columns]
        if flow_bar_cols:
            fig = styled_bar_chart(
                flow_metrics, "DT_COMPTC", flow_bar_cols,
                "Aquisicoes vs Resgates", y_format="brl",
                colors=[COLORS["success"], COLORS["danger"]],
            )
            st.plotly_chart(fig, width="stretch", key="flow_aquisicoes")

    with col2:
        if "Fluxo_Liquido" in flow_metrics.columns:
            fm = flow_metrics.copy()
            fm["Color"] = fm["Fluxo_Liquido"].apply(lambda x: COLORS["success"] if x >= 0 else COLORS["danger"])
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=fm["DT_COMPTC"], y=fm["Fluxo_Liquido"],
                marker_color=fm["Color"], name="Fluxo Liquido",
            ))
            fig.update_layout(**CHART_LAYOUT, title="Fluxo Liquido Mensal")
            fig.update_yaxes(tickformat=",.0f", tickprefix="R$ ")
            fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
            st.plotly_chart(fig, width="stretch", key="flow_liquido")

    if "Substituicoes" in flow_metrics.columns:
        fig = styled_bar_chart(
            flow_metrics, "DT_COMPTC", ["Substituicoes"],
            "Substituicoes de Direitos Creditorios", y_format="brl",
            colors=[COLORS["warning"]],
        )
        st.plotly_chart(fig, width="stretch", key="flow_substituicoes")

    with st.expander("Dados detalhados - Fluxo"):
        display_flow = flow_metrics.copy()
        display_flow["DT_COMPTC"] = display_flow["DT_COMPTC"].dt.strftime("%Y-%m")
        st.dataframe(display_flow, width="stretch", hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7: RAW DATA
# ═══════════════════════════════════════════════════════════════════════════════

with tab_data:
    st.markdown('<div class="section-header">Dados Brutos CVM</div>', unsafe_allow_html=True)

    if tables:
        table_names = list(tables.keys())
        selected_table = st.selectbox("Selecione a tabela:", table_names)

        if selected_table:
            df = tables[selected_table]
            st.markdown(f"**{selected_table}** — {len(df)} linhas, {len(df.columns)} colunas")

            # Show column list
            with st.expander("Colunas disponiveis"):
                st.write(", ".join(df.columns.tolist()))

            # Display data
            display_df = df.copy()
            if "DT_COMPTC" in display_df.columns:
                display_df["DT_COMPTC"] = pd.to_datetime(display_df["DT_COMPTC"]).dt.strftime("%Y-%m-%d")
            # Fix mixed-type columns that cause Arrow serialization errors
            for col in display_df.columns:
                if display_df[col].dtype == "object":
                    display_df[col] = display_df[col].astype(str)
            st.dataframe(display_df, width="stretch", hide_index=True)

            # Download button
            csv = display_df.to_csv(index=False, sep=";")
            st.download_button(
                "Download CSV",
                csv,
                file_name=f"{selected_table}.csv",
                mime="text/csv",
            )
    else:
        st.warning("Nenhuma tabela disponivel.")


# ── Full KPI export ──────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("---")
    st.markdown("##### Exportar")
    if not kpi_df.empty:
        export_df = kpi_df.copy()
        if "DT_COMPTC" in export_df.columns:
            export_df["DT_COMPTC"] = export_df["DT_COMPTC"].dt.strftime("%Y-%m")
        csv_export = export_df.to_csv(index=False, sep=";")
        st.download_button(
            "Download KPIs (CSV)",
            csv_export,
            file_name=f"{fund_name.lower().replace(' ', '_')}_kpis.csv",
            mime="text/csv",
            width="stretch",
        )

        # Bulk export: all analytics in one file
        import io
        buf = io.BytesIO()
        fn_safe = fund_name.lower().replace(" ", "_")
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            export_df.to_excel(writer, sheet_name="KPIs", index=False)
            if not credit_quality.empty:
                cq_exp = credit_quality.copy()
                cq_exp["DT_COMPTC"] = cq_exp["DT_COMPTC"].dt.strftime("%Y-%m")
                cq_exp.to_excel(writer, sheet_name="Qualidade Credito", index=False)
            if sub_ratios is not None and not sub_ratios.empty:
                sr_exp = sub_ratios.copy()
                sr_exp["DT_COMPTC"] = sr_exp["DT_COMPTC"].dt.strftime("%Y-%m")
                sr_exp.to_excel(writer, sheet_name="Subordinacao", index=False)
            if not spread_metrics.empty:
                sp_exp = spread_metrics.copy()
                sp_exp["DT_COMPTC"] = sp_exp["DT_COMPTC"].dt.strftime("%Y-%m")
                sp_exp.to_excel(writer, sheet_name="Performance", index=False)
            if not flow_metrics.empty:
                fl_exp = flow_metrics.copy()
                fl_exp["DT_COMPTC"] = fl_exp["DT_COMPTC"].dt.strftime("%Y-%m")
                fl_exp.to_excel(writer, sheet_name="Fluxo", index=False)
        buf.seek(0)
        st.download_button(
            "Download Completo (Excel)",
            buf.getvalue(),
            file_name=f"{fn_safe}_relatorio_completo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
