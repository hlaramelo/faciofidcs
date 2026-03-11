#!/usr/bin/env python3
"""Facio FIDC Monitoring Dashboard — Professional credit investor view.

Run with: streamlit run dashboard.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from config import DATA_DIR, DEFAULT_MONTHS_BACK, FUNDS
from src.analytics import (
    compute_credit_quality_metrics,
    compute_flow_metrics,
    compute_performance_metrics,
    compute_subordination_ratios,
    fetch_cdi_monthly,
    format_brl,
    format_pct,
    get_alert_flags,
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
    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
    margin=dict(l=40, r=20, t=50, b=40),
    hovermode="x unified",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
)


def styled_line_chart(df, x, y_cols, title, y_format=None, colors=None):
    """Create a clean line chart."""
    fig = go.Figure()
    palette = colors or [COLORS["primary"], COLORS["warning"], COLORS["danger"], COLORS["info"]]
    for i, col in enumerate(y_cols):
        if col not in df.columns:
            continue
        fig.add_trace(go.Scatter(
            x=df[x], y=df[col], name=col, mode="lines+markers",
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
    for i, col in enumerate(y_cols):
        if col not in df.columns:
            continue
        fig.add_trace(go.Bar(
            x=df[x], y=df[col], name=col,
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
    """Create a clean stacked area chart."""
    fig = go.Figure()
    palette = colors or [COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]]
    for i, col in enumerate(y_cols):
        if col not in df.columns:
            continue
        fig.add_trace(go.Scatter(
            x=df[x], y=df[col], name=col, mode="lines",
            fill="tonexty" if i > 0 else "tozeroy",
            line=dict(color=palette[i % len(palette)], width=1),
            fillcolor=_hex_to_rgba(palette[i % len(palette)], 0.25),
        ))
    fig.update_layout(**CHART_LAYOUT, title=title)
    if y_format == "brl":
        fig.update_yaxes(tickformat=",.0f", tickprefix="R$ ")
    elif y_format == "pct":
        fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
    return fig


# ── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_data(start_str: str, end_str: str, cnpj_raw: str):
    """Download, parse, and extract KPIs for a single fund. Cached for 1 hour."""
    from datetime import date as d

    start_parts = start_str.split("-")
    end_parts = end_str.split("-")
    start_date = d(int(start_parts[0]), int(start_parts[1]), 1)
    end_date = d(int(end_parts[0]), int(end_parts[1]), 1)

    data_dirs = download_monthly_zips(start_date, end_date)
    if not data_dirs:
        return None, None, None, None

    tables = parse_all_tables(data_dirs, [cnpj_raw])
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

    return kpi_df, tables, per_class, cdi_df


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Facio FIDC Monitor")
    st.markdown("---")

    fund_names = [f["name"] for f in FUNDS]
    selected_fund_name = st.selectbox("Fundo", fund_names)
    selected_fund = next(f for f in FUNDS if f["name"] == selected_fund_name)
    fund_name = selected_fund["name"]
    st.markdown(f"**CNPJ:** {selected_fund['cnpj']}")

    st.markdown("---")
    st.markdown("##### Periodo de Analise")

    today = date.today()
    default_start = today - timedelta(days=DEFAULT_MONTHS_BACK * 31)

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        start_month = st.date_input(
            "De",
            value=default_start.replace(day=1),
            format="YYYY-MM-DD",
        )
    with col_s2:
        end_month = st.date_input(
            "Ate",
            value=today.replace(day=1),
            format="YYYY-MM-DD",
        )

    refresh = st.button("Atualizar Dados", type="primary", use_container_width=True)

    st.markdown("---")
    st.markdown(
        "<small style='color:#94a3b8'>Dados: CVM Portal de Dados Abertos<br>"
        "Informes Mensais de FIDC</small>",
        unsafe_allow_html=True,
    )


# ── Load data ────────────────────────────────────────────────────────────────

start_str = start_month.strftime("%Y-%m")
end_str = end_month.strftime("%Y-%m")

with st.spinner("Carregando dados do CVM..."):
    kpi_df, tables, per_class, cdi_df = load_data(start_str, end_str, selected_fund["cnpj_raw"])

if kpi_df is None or kpi_df.empty:
    st.error("Nenhum dado disponivel. Verifique a conexao e o periodo selecionado.")
    st.stop()

# Force clear cache on refresh button
if refresh:
    load_data.clear()
    st.rerun()

# ── Compute all analytics ───────────────────────────────────────────────────

per_class = per_class or {}
credit_quality = compute_credit_quality_metrics(kpi_df)
flow_metrics = compute_flow_metrics(kpi_df)
perf_metrics = compute_performance_metrics(kpi_df, per_class)
sub_ratios = compute_subordination_ratios(per_class)
alerts = get_alert_flags(kpi_df, per_class)

latest = kpi_df.iloc[-1]
prev = kpi_df.iloc[-2] if len(kpi_df) > 1 else None

latest_date = kpi_df["DT_COMPTC"].max()
date_label = latest_date.strftime("%b/%Y") if pd.notna(latest_date) else "N/A"

# ── Header ───────────────────────────────────────────────────────────────────

st.markdown(f"## {fund_name}")
st.markdown(f"Dados ate **{date_label}** · {len(kpi_df)} meses de historico")

# ── Alerts ───────────────────────────────────────────────────────────────────

for alert in alerts:
    icon = {"danger": "🔴", "warning": "🟡", "info": "🟢"}[alert["level"]]
    st.markdown(
        f'<div class="alert-{alert["level"]}">{icon} {alert["message"]}</div>',
        unsafe_allow_html=True,
    )

st.markdown("")

# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_overview, tab_credit, tab_subordination, tab_performance, tab_flow, tab_data = st.tabs([
    "Visao Geral",
    "Qualidade de Credito",
    "Subordinacao",
    "Performance",
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
        st.metric("Aquisicoes", format_brl(latest.get("AQUISICOES")), _delta("AQUISICOES"))
    with c7:
        st.metric("Resgates", format_brl(latest.get("RESGATES")), _delta("RESGATES"))
    with c8:
        rentab = latest.get("RENTAB_MES")
        st.metric("Rentabilidade Mensal", format_pct(rentab), None)

    st.markdown("")

    # Row 3: Charts
    col_left, col_right = st.columns(2)

    with col_left:
        if "PL" in perf_metrics.columns:
            fig = styled_line_chart(
                perf_metrics, "DT_COMPTC", ["PL"],
                "Patrimonio Liquido", y_format="brl",
            )
            st.plotly_chart(fig, use_container_width=True, key="overview_pl")

    with col_right:
        if "Taxa_Inadimplencia_%" in credit_quality.columns:
            fig = styled_line_chart(
                credit_quality, "DT_COMPTC", ["Taxa_Inadimplencia_%"],
                "Taxa de Inadimplencia", y_format="pct",
                colors=[COLORS["danger"]],
            )
            st.plotly_chart(fig, use_container_width=True, key="overview_inadimplencia")

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
                st.plotly_chart(fig, use_container_width=True, key="overview_subordinacao")

    with col_right2:
        cota_df = per_class.get("cota_por_classe")
        if cota_df is not None and not cota_df.empty:
            cota_cols = [c for c in cota_df.columns if c != "DT_COMPTC"]
            fig = styled_line_chart(
                cota_df, "DT_COMPTC", cota_cols,
                "Valor da Cota por Classe", y_format="brl",
                colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
            )
            st.plotly_chart(fig, use_container_width=True, key="overview_cota")


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
        if "Taxa_Inadimplencia_%" in credit_quality.columns:
            fig = styled_line_chart(
                credit_quality, "DT_COMPTC", ["Taxa_Inadimplencia_%"],
                "Evolucao da Taxa de Inadimplencia", y_format="pct",
                colors=[COLORS["danger"]],
            )
            st.plotly_chart(fig, use_container_width=True, key="credit_inadimplencia")

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
            st.plotly_chart(fig, use_container_width=True, key="credit_performar")

    col3, col4 = st.columns(2)

    with col3:
        # Provisioning coverage
        if "Cobertura_Provisao_%" in credit_quality.columns:
            fig = styled_line_chart(
                credit_quality, "DT_COMPTC", ["Cobertura_Provisao_%"],
                "Cobertura de Provisao (%)", y_format="pct",
                colors=[COLORS["info"]],
            )
            st.plotly_chart(fig, use_container_width=True, key="credit_cobertura")

    with col4:
        # MoM change in default rate
        if "Inadimplencia_MoM_pp" in credit_quality.columns:
            fig = styled_bar_chart(
                credit_quality, "DT_COMPTC", ["Inadimplencia_MoM_pp"],
                "Variacao Mensal Inadimplencia (pp)", y_format="pct",
                colors=[COLORS["warning"]],
            )
            st.plotly_chart(fig, use_container_width=True, key="credit_mom")

    # Data table
    with st.expander("Dados detalhados - Qualidade de Credito"):
        display_cq = credit_quality.copy()
        display_cq["DT_COMPTC"] = display_cq["DT_COMPTC"].dt.strftime("%Y-%m")
        st.dataframe(display_cq, use_container_width=True, hide_index=True)


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
                st.plotly_chart(fig, use_container_width=True, key="sub_ratio")

        with col2:
            # PL composition over time (stacked area)
            if sub_class_filter:
                fig = styled_area_chart(
                    sub_ratios, "DT_COMPTC", sub_class_filter,
                    "Composicao do PL por Classe", y_format="brl",
                    colors=[COLORS["senior"], COLORS["mezanino"], COLORS["subordinada"]],
                )
                st.plotly_chart(fig, use_container_width=True, key="sub_pl_classe")

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
                st.plotly_chart(fig, use_container_width=True, key="sub_pie")

            with col_table:
                with st.expander("Dados detalhados - Subordinacao", expanded=True):
                    display_sub = sub_ratios.copy()
                    display_sub["DT_COMPTC"] = display_sub["DT_COMPTC"].dt.strftime("%Y-%m")
                    st.dataframe(display_sub, use_container_width=True, hide_index=True)
    else:
        st.info("Dados de subordinacao por classe nao disponiveis para o periodo selecionado.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════════════

with tab_performance:
    st.markdown('<div class="section-header">Performance do Fundo</div>', unsafe_allow_html=True)

    perf_latest = perf_metrics.iloc[-1] if not perf_metrics.empty else {}

    # Summary cards
    pc1, pc2, pc3, pc4 = st.columns(4)
    with pc1:
        st.metric("PL", format_brl(perf_latest.get("PL")))
    with pc2:
        st.metric("Ativo Total", format_brl(perf_latest.get("Ativo_Total")))
    with pc3:
        st.metric("Rentabilidade Mensal", format_pct(perf_latest.get("Rentabilidade_%")))
    with pc4:
        st.metric("Valor da Cota", format_brl(perf_latest.get("Valor_Cota")))

    st.markdown("")

    col1, col2 = st.columns(2)

    with col1:
        if "PL" in perf_metrics.columns:
            fig = styled_area_chart(
                perf_metrics, "DT_COMPTC", ["PL"],
                "Evolucao do Patrimonio Liquido", y_format="brl",
                colors=[COLORS["primary"]],
            )
            st.plotly_chart(fig, use_container_width=True, key="perf_pl")

    with col2:
        # Rentabilidade vs CDI benchmark
        if "Rentabilidade_%" in perf_metrics.columns:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=perf_metrics["DT_COMPTC"], y=perf_metrics["Rentabilidade_%"],
                name="Fundo", marker_color=COLORS["success"], opacity=0.9,
            ))
            if cdi_df is not None and not cdi_df.empty:
                merged_cdi = perf_metrics[["DT_COMPTC"]].merge(
                    cdi_df, on="DT_COMPTC", how="left",
                )
                if "CDI_%" in merged_cdi.columns and merged_cdi["CDI_%"].notna().any():
                    fig.add_trace(go.Scatter(
                        x=merged_cdi["DT_COMPTC"], y=merged_cdi["CDI_%"],
                        name="CDI", mode="lines+markers",
                        line=dict(color=COLORS["warning"], width=2.5, dash="dot"),
                        marker=dict(size=5),
                    ))
            fig.update_layout(**CHART_LAYOUT, title="Rentabilidade Mensal vs CDI")
            fig.update_yaxes(ticksuffix="%")
            fig.update_xaxes(dtick="M1", tickformat="%b/%Y")
            st.plotly_chart(fig, use_container_width=True, key="perf_rentab")

    col3, col4 = st.columns(2)

    with col3:
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
                st.plotly_chart(fig, use_container_width=True, key="perf_cota")

    with col4:
        if "Nr_Cotistas" in perf_metrics.columns:
            fig = styled_line_chart(
                perf_metrics, "DT_COMPTC", ["Nr_Cotistas"],
                "Numero de Cotistas", colors=[COLORS["info"]],
            )
            st.plotly_chart(fig, use_container_width=True, key="perf_cotistas")

    with st.expander("Dados detalhados - Performance"):
        display_perf = perf_metrics.copy()
        display_perf["DT_COMPTC"] = display_perf["DT_COMPTC"].dt.strftime("%Y-%m")
        st.dataframe(display_perf, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5: PORTFOLIO FLOW
# ═══════════════════════════════════════════════════════════════════════════════

with tab_flow:
    st.markdown('<div class="section-header">Fluxo da Carteira</div>', unsafe_allow_html=True)

    flow_latest = flow_metrics.iloc[-1] if not flow_metrics.empty else {}

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
            st.plotly_chart(fig, use_container_width=True, key="flow_aquisicoes")

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
            st.plotly_chart(fig, use_container_width=True, key="flow_liquido")

    if "Substituicoes" in flow_metrics.columns:
        fig = styled_bar_chart(
            flow_metrics, "DT_COMPTC", ["Substituicoes"],
            "Substituicoes de Direitos Creditorios", y_format="brl",
            colors=[COLORS["warning"]],
        )
        st.plotly_chart(fig, use_container_width=True, key="flow_substituicoes")

    with st.expander("Dados detalhados - Fluxo"):
        display_flow = flow_metrics.copy()
        display_flow["DT_COMPTC"] = display_flow["DT_COMPTC"].dt.strftime("%Y-%m")
        st.dataframe(display_flow, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6: RAW DATA
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
            st.dataframe(display_df, use_container_width=True, hide_index=True)

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
            use_container_width=True,
        )
