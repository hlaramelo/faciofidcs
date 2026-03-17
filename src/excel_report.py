"""Generates Excel reports with formatted sheets and charts."""

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import AreaChart, BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side, numbers
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows

# Styles
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
BRL_FORMAT = '#,##0.00'
PCT_FORMAT = '0.00"%"'
INTEGER_FORMAT = '#,##0'

# KPI display names (Portuguese)
KPI_DISPLAY_NAMES = {
    "PL": "Patrimonio Liquido (R$)",
    "ATIVO_TOTAL": "Ativo Total (R$)",
    "VALOR_COTA": "Valor da Cota (R$)",
    "NR_COTISTAS": "Numero de Cotistas",
    "DC_PERFORMAR": "Direitos Creditorios - Performar (R$)",
    "DC_NAO_PERFORMAR": "Direitos Creditorios - Nao Performar (R$)",
    "AQUISICOES": "Aquisicoes no Periodo (R$)",
    "RESGATES": "Resgates no Periodo (R$)",
    "RENTAB_MES": "Rentabilidade Mensal (%)",
    "INADIMPLENCIA_VL": "Inadimplencia - Valor (R$)",
    "INADIMPLENCIA_PROVISAO": "Provisao para Perdas (R$)",
    "SUBSTITUICAO": "Substituicao de DC (R$)",
    "TAXA_INADIMPLENCIA": "Taxa de Inadimplencia (%)",
}


def style_header_row(ws, row_num: int, num_cols: int):
    """Apply header styling to a row."""
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row_num, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGNMENT
        cell.border = THIN_BORDER


def auto_column_width(ws, min_width: int = 12, max_width: int = 35):
    """Auto-adjust column widths based on content."""
    for col_cells in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        adjusted = min(max(max_length + 2, min_width), max_width)
        ws.column_dimensions[col_letter].width = adjusted


def format_number_cells(ws, start_row: int, num_rows: int, num_cols: int):
    """Apply number formatting to data cells."""
    for row in range(start_row, start_row + num_rows):
        for col in range(1, num_cols + 1):
            cell = ws.cell(row=row, column=col)
            cell.border = THIN_BORDER
            if isinstance(cell.value, (int, float)):
                header = ws.cell(row=start_row - 1, column=col).value or ""
                header_upper = str(header).upper()
                if "MOM" in header_upper or "%" in header_upper:
                    cell.number_format = PCT_FORMAT
                elif "NR_" in header_upper or "QT_" in header_upper or "COTIST" in header_upper:
                    cell.number_format = INTEGER_FORMAT
                else:
                    cell.number_format = BRL_FORMAT


def write_dashboard(wb: Workbook, kpi_df: pd.DataFrame, fund_name: str):
    """Create the Dashboard summary sheet."""
    ws = wb.active
    ws.title = "Dashboard"

    # Title
    ws.merge_cells("A1:F1")
    title_cell = ws["A1"]
    title_cell.value = f"FIDC Monitor - {fund_name}"
    title_cell.font = Font(name="Calibri", bold=True, size=16, color="2F5496")
    title_cell.alignment = Alignment(horizontal="center")

    if kpi_df.empty:
        ws["A3"] = "Nenhum dado disponivel. Verifique a conexao com o portal CVM."
        return

    # Freeze below title
    ws.freeze_panes = "A5"

    # Latest date
    latest_date = kpi_df["DT_COMPTC"].max()
    ws["A3"] = f"Dados ate: {latest_date.strftime('%B/%Y') if pd.notna(latest_date) else 'N/A'}"
    ws["A3"].font = Font(name="Calibri", size=11, italic=True)

    # Summary table
    row = 5
    ws.cell(row=row, column=1, value="Indicador")
    ws.cell(row=row, column=2, value="Ultimo Valor")
    ws.cell(row=row, column=3, value="Variacao MoM")
    style_header_row(ws, row, 3)

    numeric_cols = [
        c
        for c in kpi_df.columns
        if c not in ["DT_COMPTC", "CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE", "DENOM_SOCIAL", "CLASSE", "CNPJ_CLASSE"]
        and not c.endswith("_MoM_%")
    ]

    latest = kpi_df.iloc[-1] if len(kpi_df) > 0 else None
    for col in numeric_cols:
        if latest is None:
            continue
        val = latest.get(col)
        if pd.isna(val):
            continue

        row += 1
        display_name = KPI_DISPLAY_NAMES.get(col, col)
        ws.cell(row=row, column=1, value=display_name)
        ws.cell(row=row, column=1).font = Font(name="Calibri", bold=True)

        value_cell = ws.cell(row=row, column=2, value=val)
        col_upper = col.upper()
        if "NR_" in col_upper or "QT_" in col_upper or "COTIST" in col_upper:
            value_cell.number_format = INTEGER_FORMAT
        elif "TAXA" in col_upper or "RENTAB" in col_upper:
            value_cell.number_format = '0.00"%"'
        else:
            value_cell.number_format = BRL_FORMAT
        value_cell.border = THIN_BORDER

        mom_col = f"{col}_MoM_%"
        if mom_col in kpi_df.columns:
            mom_val = latest.get(mom_col)
            if pd.notna(mom_val):
                mom_cell = ws.cell(row=row, column=3, value=mom_val / 100)
                mom_cell.number_format = "0.00%"
                mom_cell.border = THIN_BORDER
                # Color: green for positive, red for negative
                if mom_val > 0:
                    mom_cell.font = Font(color="006100")
                elif mom_val < 0:
                    mom_cell.font = Font(color="9C0006")

    auto_column_width(ws)


def write_time_series_sheet(
    wb: Workbook,
    kpi_df: pd.DataFrame,
    sheet_name: str,
    value_columns: list[str],
    chart_title: str,
    chart_type: str = "area",
):
    """Create a time series sheet with data and chart."""
    ws = wb.create_sheet(title=sheet_name)

    if kpi_df.empty:
        ws["A1"] = "Sem dados disponiveis"
        return

    # Filter to available columns
    available_cols = [c for c in value_columns if c in kpi_df.columns]
    if not available_cols:
        ws["A1"] = f"Colunas nao encontradas: {', '.join(value_columns)}"
        return

    # Skip sheet if all value columns are entirely NaN
    if kpi_df[available_cols].isna().all().all():
        ws["A1"] = "Sem dados disponiveis para este indicador"
        return

    # Write data
    display_cols = ["DT_COMPTC"] + available_cols
    subset = kpi_df[display_cols].copy()
    subset["DT_COMPTC"] = subset["DT_COMPTC"].dt.strftime("%Y-%m")

    # Headers
    for col_idx, col_name in enumerate(display_cols, 1):
        display_name = KPI_DISPLAY_NAMES.get(col_name, col_name)
        ws.cell(row=1, column=col_idx, value=display_name)
    style_header_row(ws, 1, len(display_cols))

    # Determine which columns are percentage-based
    pct_keywords = {"RENTAB", "%", "PCT", "TAXA"}

    # Data rows
    for row_idx, (_, data_row) in enumerate(subset.iterrows(), 2):
        for col_idx, col_name in enumerate(display_cols, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=data_row[col_name])
            cell.border = THIN_BORDER
            if col_idx > 1 and isinstance(cell.value, (int, float)):
                display_name = KPI_DISPLAY_NAMES.get(col_name, col_name).upper()
                if any(kw in col_name.upper() or kw in display_name for kw in pct_keywords):
                    cell.number_format = '0.00"%"'
                elif "NR_" in col_name.upper() or "QT_" in col_name.upper():
                    cell.number_format = INTEGER_FORMAT
                else:
                    cell.number_format = BRL_FORMAT

    num_data_rows = len(subset)
    auto_column_width(ws)

    if num_data_rows < 2:
        return

    # Create chart
    chart = _create_styled_chart(chart_type, chart_title)

    # Categories (dates)
    cats = Reference(ws, min_col=1, min_row=2, max_row=1 + num_data_rows)
    chart.set_categories(cats)

    # Data series
    for i, col_idx in enumerate(range(2, len(display_cols) + 1)):
        data = Reference(ws, min_col=col_idx, min_row=1, max_row=1 + num_data_rows)
        chart.add_data(data, titles_from_data=True)
    _style_chart_series(chart)

    # Place chart to the right of data
    chart_col = get_column_letter(len(display_cols) + 2)
    ws.add_chart(chart, f"{chart_col}1")

    # Freeze header row
    ws.freeze_panes = "A2"


def write_per_class_sheet(
    wb: Workbook,
    class_df: pd.DataFrame,
    sheet_name: str,
    chart_title: str,
    chart_type: str = "line",
):
    """Create a sheet with per-class time series data and chart.

    class_df should have DT_COMPTC as first column and one column per class.
    """
    ws = wb.create_sheet(title=sheet_name[:31])

    if class_df is None or class_df.empty:
        ws["A1"] = "Sem dados disponiveis"
        return

    value_cols = [c for c in class_df.columns if c != "DT_COMPTC"]
    if not value_cols:
        ws["A1"] = "Sem dados disponiveis"
        return

    # Skip if all values are NaN
    if class_df[value_cols].isna().all().all():
        ws["A1"] = "Sem dados disponiveis para este indicador"
        return

    # Write headers
    display_cols = ["DT_COMPTC"] + value_cols
    subset = class_df[display_cols].copy()
    subset["DT_COMPTC"] = pd.to_datetime(subset["DT_COMPTC"]).dt.strftime("%Y-%m")

    ws.cell(row=1, column=1, value="Mes")
    for col_idx, col_name in enumerate(value_cols, 2):
        ws.cell(row=1, column=col_idx, value=col_name)
    style_header_row(ws, 1, len(display_cols))

    # Detect column type from sheet/column names for proper formatting
    sheet_upper = sheet_name.upper()
    is_cota = "COTA" in sheet_upper
    is_cotistas = "COTIST" in sheet_upper
    is_pct = any(kw in sheet_upper for kw in ["%", "RENTAB", "TAXA", "SUBORDIN"])

    # Data rows
    for row_idx, (_, data_row) in enumerate(subset.iterrows(), 2):
        ws.cell(row=row_idx, column=1, value=data_row["DT_COMPTC"]).border = THIN_BORDER
        for col_idx, col_name in enumerate(value_cols, 2):
            cell = ws.cell(row=row_idx, column=col_idx, value=data_row[col_name])
            cell.border = THIN_BORDER
            if isinstance(cell.value, (int, float)):
                col_upper = col_name.upper()
                if is_cota or "COTA" in col_upper:
                    cell.number_format = '#,##0.000000'
                elif is_cotistas or "COTIST" in col_upper:
                    cell.number_format = INTEGER_FORMAT
                elif is_pct or "%" in col_upper or "RENTAB" in col_upper:
                    cell.number_format = PCT_FORMAT
                else:
                    cell.number_format = BRL_FORMAT

    num_data_rows = len(subset)
    auto_column_width(ws)

    if num_data_rows < 2:
        return

    # Create chart
    chart = _create_styled_chart(chart_type, chart_title)

    cats = Reference(ws, min_col=1, min_row=2, max_row=1 + num_data_rows)
    chart.set_categories(cats)

    for i, col_idx in enumerate(range(2, len(display_cols) + 1)):
        data = Reference(ws, min_col=col_idx, min_row=1, max_row=1 + num_data_rows)
        chart.add_data(data, titles_from_data=True)
    _style_chart_series(chart)

    chart_col = get_column_letter(len(display_cols) + 2)
    ws.add_chart(chart, f"{chart_col}1")

    ws.freeze_panes = "A2"


CHART_COLORS = ["2F5496", "ED7D31", "70AD47", "FFC000", "5B9BD5", "A5A5A5", "264478", "C55A11"]


def _create_styled_chart(chart_type: str, title: str):
    """Create a chart with consistent styling."""
    if chart_type == "area":
        chart = AreaChart()
    elif chart_type == "bar":
        chart = BarChart()
        chart.grouping = "stacked"
    else:
        chart = LineChart()

    chart.style = 10
    chart.title = title
    chart.x_axis.title = "Mes"

    # Y-axis label based on data type
    title_upper = title.upper()
    if any(kw in title_upper for kw in ["RENTAB", "%", "TAXA", "INADIMP"]):
        chart.y_axis.title = "%"
        chart.y_axis.numFmt = '0.00"%"'
    elif "COTA" in title_upper:
        chart.y_axis.title = "Valor da Cota"
        chart.y_axis.numFmt = '#,##0.000000'
    elif "COTIST" in title_upper:
        chart.y_axis.title = "Cotistas"
        chart.y_axis.numFmt = '#,##0'
    else:
        chart.y_axis.title = "Valor (R$)"
        chart.y_axis.numFmt = '#,##0'

    chart.width = 30
    chart.height = 16
    chart.legend.position = "b"
    chart.y_axis.crossAx = 100
    chart.x_axis.tickLblPos = "low"
    chart.x_axis.delete = False
    chart.x_axis.txPr = None  # Reset any text properties
    chart.x_axis.numFmt = "General"
    chart.x_axis.majorTickMark = "out"
    chart.x_axis.tickLblSkip = 1  # Show every label

    # Smooth lines for line charts
    if chart_type == "line":
        chart.style = 12

    return chart


def _style_chart_series(chart):
    """Apply consistent colors and styling to chart series."""
    for i, series in enumerate(chart.series):
        if i < len(CHART_COLORS):
            series.graphicalProperties.solidFill = CHART_COLORS[i]
            # For line charts, also set line color
            if hasattr(series, 'graphicalProperties') and hasattr(series.graphicalProperties, 'line'):
                series.graphicalProperties.line.solidFill = CHART_COLORS[i]
                series.graphicalProperties.line.width = 22000  # ~2pt


def write_raw_data_sheet(wb: Workbook, tables: dict[str, pd.DataFrame]):
    """Write raw data sheets for reference."""
    for table_name, df in tables.items():
        if df.empty:
            continue

        # Sanitize sheet name (max 31 chars, no special chars)
        sheet_name = f"Raw_{table_name}"[:31]
        ws = wb.create_sheet(title=sheet_name)

        # Write headers
        for col_idx, col_name in enumerate(df.columns, 1):
            ws.cell(row=1, column=col_idx, value=col_name)
        style_header_row(ws, 1, len(df.columns))

        # Write data
        for row_idx, (_, data_row) in enumerate(df.iterrows(), 2):
            for col_idx, col_name in enumerate(df.columns, 1):
                val = data_row[col_name]
                if pd.isna(val):
                    val = ""
                ws.cell(row=row_idx, column=col_idx, value=val)

        auto_column_width(ws)


def write_analytics_sheet(
    wb: Workbook,
    df: pd.DataFrame,
    sheet_name: str,
    chart_title: str,
    chart_cols: list[str] | None = None,
    chart_type: str = "line",
):
    """Create a sheet from an analytics DataFrame with auto-formatted data and chart.

    This is similar to write_time_series_sheet but works with analytics DataFrames
    that have descriptive column names (not raw CVM names).
    """
    ws = wb.create_sheet(title=sheet_name[:31])

    if df is None or df.empty:
        ws["A1"] = "Sem dados disponiveis"
        return

    # Determine columns to display
    display_cols = [c for c in df.columns if c != "_year"]
    if not display_cols:
        ws["A1"] = "Sem dados disponiveis"
        return

    # Determine which columns to chart
    if chart_cols:
        chart_value_cols = [c for c in chart_cols if c in df.columns and c != "DT_COMPTC"]
    else:
        chart_value_cols = [c for c in display_cols if c != "DT_COMPTC"]

    # Skip if all chart columns are entirely NaN
    if chart_value_cols and df[chart_value_cols].isna().all().all():
        ws["A1"] = "Sem dados disponiveis para este indicador"
        return

    subset = df[display_cols].copy()
    if "DT_COMPTC" in subset.columns:
        subset["DT_COMPTC"] = pd.to_datetime(subset["DT_COMPTC"], errors="coerce").dt.strftime("%Y-%m")

    # Headers
    for col_idx, col_name in enumerate(display_cols, 1):
        ws.cell(row=1, column=col_idx, value=col_name)
    style_header_row(ws, 1, len(display_cols))

    # Detect percentage columns
    pct_keywords = {"%", "PCT", "TAXA", "RENTAB", "SPREAD", "SHARPE", "VOL", "SUBORDIN"}

    # Data rows
    for row_idx, (_, data_row) in enumerate(subset.iterrows(), 2):
        for col_idx, col_name in enumerate(display_cols, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=data_row[col_name])
            cell.border = THIN_BORDER
            if col_idx > 1 and isinstance(cell.value, (int, float)):
                col_upper = col_name.upper()
                if any(kw in col_upper for kw in pct_keywords):
                    cell.number_format = '0.00"%"'
                elif "NR_" in col_upper or "COTIST" in col_upper:
                    cell.number_format = INTEGER_FORMAT
                elif "COMPLIANT" in col_upper or col_name in ("True", "False"):
                    pass  # Leave as-is for booleans
                else:
                    cell.number_format = BRL_FORMAT

    num_data_rows = len(subset)
    auto_column_width(ws)

    if num_data_rows < 2 or not chart_value_cols:
        ws.freeze_panes = "A2"
        return

    # Create chart
    chart = _create_styled_chart(chart_type, chart_title)

    # Categories (dates)
    cats = Reference(ws, min_col=1, min_row=2, max_row=1 + num_data_rows)
    chart.set_categories(cats)

    # Data series — only chart the specified columns
    for col_name in chart_value_cols:
        if col_name in display_cols:
            col_idx = display_cols.index(col_name) + 1
            data = Reference(ws, min_col=col_idx, min_row=1, max_row=1 + num_data_rows)
            chart.add_data(data, titles_from_data=True)
    _style_chart_series(chart)

    chart_col = get_column_letter(len(display_cols) + 2)
    ws.add_chart(chart, f"{chart_col}1")

    ws.freeze_panes = "A2"


def write_alerts_sheet(wb: Workbook, alerts: list[dict], fund_name: str):
    """Create an alerts summary sheet."""
    ws = wb.create_sheet(title="Alertas")

    ws.merge_cells("A1:C1")
    title_cell = ws["A1"]
    title_cell.value = f"Alertas - {fund_name}"
    title_cell.font = Font(name="Calibri", bold=True, size=14, color="2F5496")

    if not alerts:
        ws["A3"] = "Nenhum alerta identificado."
        return

    # Headers
    ws.cell(row=3, column=1, value="Nivel")
    ws.cell(row=3, column=2, value="Indicador")
    ws.cell(row=3, column=3, value="Mensagem")
    style_header_row(ws, 3, 3)

    level_colors = {
        "danger": "9C0006",
        "warning": "9C6500",
        "info": "006100",
    }
    level_fills = {
        "danger": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
        "warning": PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
        "info": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
    }

    for row_idx, alert in enumerate(alerts, 4):
        level = alert.get("level", "info")
        ws.cell(row=row_idx, column=1, value=level.upper())
        ws.cell(row=row_idx, column=1).font = Font(bold=True, color=level_colors.get(level, "000000"))
        ws.cell(row=row_idx, column=1).fill = level_fills.get(level, PatternFill())
        ws.cell(row=row_idx, column=2, value=alert.get("metric", ""))
        ws.cell(row=row_idx, column=3, value=alert.get("message", ""))
        for col in range(1, 4):
            ws.cell(row=row_idx, column=col).border = THIN_BORDER

    auto_column_width(ws)


def write_covenant_sheet(wb: Workbook, covenant_df: pd.DataFrame):
    """Create a covenant compliance heatmap sheet."""
    ws = wb.create_sheet(title="Covenants")

    if covenant_df is None or covenant_df.empty:
        ws["A1"] = "Sem dados de covenants disponiveis"
        return

    display_cols = list(covenant_df.columns)
    subset = covenant_df.copy()
    if "DT_COMPTC" in subset.columns:
        subset["DT_COMPTC"] = pd.to_datetime(subset["DT_COMPTC"], errors="coerce").dt.strftime("%Y-%m")

    # Headers
    for col_idx, col_name in enumerate(display_cols, 1):
        ws.cell(row=1, column=col_idx, value=col_name)
    style_header_row(ws, 1, len(display_cols))

    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

    for row_idx, (_, data_row) in enumerate(subset.iterrows(), 2):
        for col_idx, col_name in enumerate(display_cols, 1):
            val = data_row[col_name]
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = THIN_BORDER
            # Color boolean covenant cells
            if col_idx > 1 and isinstance(val, (bool,)):
                cell.value = "OK" if val else "BREACH"
                cell.fill = green_fill if val else red_fill
                cell.font = Font(bold=True, color="006100" if val else "9C0006")
                cell.alignment = Alignment(horizontal="center")

    auto_column_width(ws)
    ws.freeze_panes = "A2"


def generate_report(
    kpi_df: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    output_path: Path,
    fund_name: str = "Facio FIDC Financeiros RL",
    per_class: dict[str, pd.DataFrame] | None = None,
    analytics: dict | None = None,
):
    """Generate the complete Excel report with dashboard, analytics, and charts.

    Args:
        kpi_df: DataFrame with KPIs and MoM trends.
        tables: Raw parsed tables for the Raw Data sheet.
        output_path: Where to save the .xlsx file.
        fund_name: Fund display name for the title.
        per_class: Optional dict with per-class DataFrames (pl_por_classe, cota_por_classe).
        analytics: Optional dict with pre-computed analytics DataFrames:
            - credit_quality: from compute_credit_quality_metrics
            - credit_ratios_pl: from compute_credit_ratios_vs_pl
            - sub_ratios: from compute_subordination_ratios
            - perf_metrics: from compute_performance_metrics
            - spread_metrics: from compute_cdi_spread
            - flow_metrics: from compute_flow_metrics
            - pl_waterfall: from compute_pl_waterfall
            - covenant_timeline: from compute_covenant_timeline
            - maturity_buckets: from compute_maturity_buckets
            - alerts: from get_alert_flags (list of dicts)
    """
    per_class = per_class or {}
    analytics = analytics or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()

    # ── Sheet 1: Dashboard ─────────────────────────────────────────────────
    write_dashboard(wb, kpi_df, fund_name)

    # ── Sheet 2: Alerts ────────────────────────────────────────────────────
    alerts = analytics.get("alerts")
    if alerts:
        write_alerts_sheet(wb, alerts, fund_name)

    # ── Sheet 3: PL Evolution ──────────────────────────────────────────────
    pl_cols = [c for c in kpi_df.columns if c == "PL"]
    if pl_cols:
        write_time_series_sheet(
            wb, kpi_df, "PL Evolucao", pl_cols, "Patrimonio Liquido - Evolucao", "area"
        )

    # ── Sheet 4: Credit Quality ────────────────────────────────────────────
    credit_quality = analytics.get("credit_quality")
    if credit_quality is not None and not credit_quality.empty:
        cq_chart_cols = [c for c in ["Taxa_Inadimplencia_%", "Cobertura_Provisao_%"] if c in credit_quality.columns]
        write_analytics_sheet(
            wb, credit_quality, "Qualidade de Credito",
            "Taxa de Inadimplencia e Cobertura (%)",
            chart_cols=cq_chart_cols, chart_type="line",
        )

    # ── Sheet 5: Credit Ratios vs PL ──────────────────────────────────────
    credit_ratios_pl = analytics.get("credit_ratios_pl")
    if credit_ratios_pl is not None and not credit_ratios_pl.empty:
        ratio_cols = [c for c in ["Vencidos_x_PL_%", "Recompra_x_PL_%", "PDD_x_PL_%"]
                      if c in credit_ratios_pl.columns]
        write_analytics_sheet(
            wb, credit_ratios_pl, "Indicadores vs PL",
            "Vencidos, Recompra e PDD vs PL (%)",
            chart_cols=ratio_cols, chart_type="line",
        )

    # ── Sheet 6: Subordination ─────────────────────────────────────────────
    sub_ratios = analytics.get("sub_ratios")
    if sub_ratios is not None and not sub_ratios.empty:
        sub_chart_cols = [c for c in sub_ratios.columns if c.endswith("_%") and "Subordinacao" in c]
        write_analytics_sheet(
            wb, sub_ratios, "Subordinacao",
            "Razao de Subordinacao (%)",
            chart_cols=sub_chart_cols, chart_type="line",
        )

    # ── Sheet 7: Performance & CDI Spread ──────────────────────────────────
    spread_metrics = analytics.get("spread_metrics")
    if spread_metrics is not None and not spread_metrics.empty:
        spread_chart = [c for c in ["Acumulado_Fundo_%", "Acumulado_CDI_%"]
                        if c in spread_metrics.columns]
        write_analytics_sheet(
            wb, spread_metrics, "Performance vs CDI",
            "Retorno Acumulado: Fundo vs CDI (%)",
            chart_cols=spread_chart, chart_type="line",
        )

    perf_metrics = analytics.get("perf_metrics")
    if perf_metrics is not None and not perf_metrics.empty:
        perf_chart = [c for c in ["Rentabilidade_%"] if c in perf_metrics.columns]
        write_analytics_sheet(
            wb, perf_metrics, "Performance",
            "Rentabilidade Mensal (%)",
            chart_cols=perf_chart, chart_type="line",
        )

    # ── Sheet 8: Flow ──────────────────────────────────────────────────────
    flow_metrics = analytics.get("flow_metrics")
    if flow_metrics is not None and not flow_metrics.empty:
        flow_chart = [c for c in ["Aquisicoes", "Resgates", "Fluxo_Liquido"]
                      if c in flow_metrics.columns]
        write_analytics_sheet(
            wb, flow_metrics, "Fluxo",
            "Aquisicoes, Resgates e Fluxo Liquido",
            chart_cols=flow_chart, chart_type="bar",
        )

    # ── Sheet 9: PL Waterfall ──────────────────────────────────────────────
    pl_waterfall = analytics.get("pl_waterfall")
    if pl_waterfall is not None and not pl_waterfall.empty:
        wf_chart = [c for c in ["Rendimentos", "Aquisicoes", "Resgates", "Inadimplencia", "Outros"]
                     if c in pl_waterfall.columns]
        write_analytics_sheet(
            wb, pl_waterfall, "PL Waterfall",
            "Decomposicao da Variacao do PL",
            chart_cols=wf_chart, chart_type="bar",
        )

    # ── Sheet 10: Covenants ────────────────────────────────────────────────
    covenant_timeline = analytics.get("covenant_timeline")
    if covenant_timeline is not None:
        write_covenant_sheet(wb, covenant_timeline)

    # ── Sheet 11: Maturity ─────────────────────────────────────────────────
    maturity = analytics.get("maturity_buckets")
    if maturity is not None and not maturity.empty:
        mat_cols = [c for c in maturity.columns if c != "DT_COMPTC"]
        write_analytics_sheet(
            wb, maturity, "Vencimento",
            "Direitos Creditorios por Faixa de Vencimento",
            chart_cols=mat_cols, chart_type="bar",
        )

    # ── Per-class sheets ───────────────────────────────────────────────────
    if "pl_por_classe" in per_class:
        write_per_class_sheet(
            wb, per_class["pl_por_classe"],
            "PL por Classe", "Patrimonio Liquido por Classe", "area"
        )

    if "cota_por_classe" in per_class:
        write_per_class_sheet(
            wb, per_class["cota_por_classe"],
            "Cota por Classe", "Valor da Cota por Classe", "line"
        )

    if "cotistas_por_classe" in per_class:
        write_per_class_sheet(
            wb, per_class["cotistas_por_classe"],
            "Cotistas por Classe", "Numero de Cotistas por Classe", "line"
        )

    if "rentab_por_classe" in per_class:
        write_per_class_sheet(
            wb, per_class["rentab_por_classe"],
            "Rentab por Classe", "Rentabilidade Mensal por Classe (%)", "line"
        )

    # ── Raw KPI data ───────────────────────────────────────────────────────
    _write_kpi_data_sheet(wb, kpi_df)

    # ── Raw Data sheets ────────────────────────────────────────────────────
    write_raw_data_sheet(wb, tables)

    wb.save(output_path)
    print(f"\n  Report saved to: {output_path}")


def _write_kpi_data_sheet(wb: Workbook, kpi_df: pd.DataFrame):
    """Write a complete KPI data sheet with all time series."""
    ws = wb.create_sheet(title="KPIs Completo")
    if kpi_df.empty:
        ws["A1"] = "Sem dados"
        return

    # Filter out MoM columns for cleaner output
    cols = [c for c in kpi_df.columns if not c.endswith("_MoM_%") and c not in (
        "CNPJ_FUNDO", "CNPJ_FUNDO_CLASSE", "DENOM_SOCIAL", "CLASSE", "CNPJ_CLASSE",
    )]

    subset = kpi_df[cols].copy()
    if "DT_COMPTC" in subset.columns:
        subset["DT_COMPTC"] = pd.to_datetime(subset["DT_COMPTC"], errors="coerce").dt.strftime("%Y-%m")

    # Headers
    for col_idx, col_name in enumerate(cols, 1):
        display_name = KPI_DISPLAY_NAMES.get(col_name, col_name)
        ws.cell(row=1, column=col_idx, value=display_name)
    style_header_row(ws, 1, len(cols))

    # Data
    for row_idx, (_, data_row) in enumerate(subset.iterrows(), 2):
        for col_idx, col_name in enumerate(cols, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=data_row[col_name])
            cell.border = THIN_BORDER
            if col_idx > 1 and isinstance(cell.value, (int, float)):
                header_upper = col_name.upper()
                if "MOM" in header_upper or "%" in header_upper or "TAXA" in header_upper or "RENTAB" in header_upper:
                    cell.number_format = PCT_FORMAT
                elif "NR_" in header_upper or "COTIST" in header_upper:
                    cell.number_format = INTEGER_FORMAT
                else:
                    cell.number_format = BRL_FORMAT

    auto_column_width(ws)
    ws.freeze_panes = "A2"
