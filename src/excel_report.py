"""Generates Excel reports with formatted sheets and charts."""

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import AreaChart, BarChart, LineChart, Reference
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
        if "NR_" in col.upper() or "QT_" in col.upper() or "COTIST" in col.upper():
            value_cell.number_format = INTEGER_FORMAT
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
    if chart_type == "area":
        chart = AreaChart()
        chart.style = 10
    elif chart_type == "bar":
        chart = BarChart()
        chart.style = 10
        chart.grouping = "stacked"
    else:
        chart = LineChart()
        chart.style = 10

    chart.title = chart_title
    chart.x_axis.title = "Mes"
    # Use appropriate Y-axis label based on data type
    if any(kw in chart_title.upper() for kw in ["RENTAB", "%", "TAXA"]):
        chart.y_axis.title = "%"
    else:
        chart.y_axis.title = "Valor (R$)"
    chart.width = 25
    chart.height = 15

    # Categories (dates)
    cats = Reference(ws, min_col=1, min_row=2, max_row=1 + num_data_rows)
    chart.set_categories(cats)

    # Data series
    colors = ["2F5496", "ED7D31", "70AD47", "FFC000"]
    for i, col_idx in enumerate(range(2, len(display_cols) + 1)):
        data = Reference(ws, min_col=col_idx, min_row=1, max_row=1 + num_data_rows)
        chart.add_data(data, titles_from_data=True)
        if i < len(colors):
            chart.series[i].graphicalProperties.solidFill = colors[i]

    # Place chart below data
    chart_row = num_data_rows + 4
    ws.add_chart(chart, f"A{chart_row}")


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

    # Data rows
    for row_idx, (_, data_row) in enumerate(subset.iterrows(), 2):
        ws.cell(row=row_idx, column=1, value=data_row["DT_COMPTC"]).border = THIN_BORDER
        for col_idx, col_name in enumerate(value_cols, 2):
            cell = ws.cell(row=row_idx, column=col_idx, value=data_row[col_name])
            cell.border = THIN_BORDER
            if isinstance(cell.value, (int, float)):
                cell.number_format = BRL_FORMAT

    num_data_rows = len(subset)
    auto_column_width(ws)

    if num_data_rows < 2:
        return

    # Create chart
    if chart_type == "area":
        chart = AreaChart()
        chart.style = 10
    elif chart_type == "bar":
        chart = BarChart()
        chart.style = 10
        chart.grouping = "stacked"
    else:
        chart = LineChart()
        chart.style = 10

    chart.title = chart_title
    chart.x_axis.title = "Mes"
    chart.y_axis.title = "Valor (R$)"
    chart.width = 25
    chart.height = 15

    cats = Reference(ws, min_col=1, min_row=2, max_row=1 + num_data_rows)
    chart.set_categories(cats)

    colors = ["2F5496", "ED7D31", "70AD47", "FFC000", "5B9BD5", "A5A5A5"]
    for i, col_idx in enumerate(range(2, len(display_cols) + 1)):
        data = Reference(ws, min_col=col_idx, min_row=1, max_row=1 + num_data_rows)
        chart.add_data(data, titles_from_data=True)
        if i < len(colors):
            chart.series[i].graphicalProperties.solidFill = colors[i]

    chart_row = num_data_rows + 4
    ws.add_chart(chart, f"A{chart_row}")


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


def generate_report(
    kpi_df: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    output_path: Path,
    fund_name: str = "Facio FIDC Financeiros RL",
    per_class: dict[str, pd.DataFrame] | None = None,
):
    """Generate the complete Excel report with dashboard and charts.

    Args:
        kpi_df: DataFrame with KPIs and MoM trends.
        tables: Raw parsed tables for the Raw Data sheet.
        output_path: Where to save the .xlsx file.
        fund_name: Fund display name for the title.
        per_class: Optional dict with per-class DataFrames (pl_por_classe, cota_por_classe).
    """
    per_class = per_class or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()

    # Sheet 1: Dashboard
    write_dashboard(wb, kpi_df, fund_name)

    # Sheet 2: PL Evolution
    pl_cols = [c for c in kpi_df.columns if "PL" in c.upper() or "PATRIM" in c.upper()]
    pl_cols = [c for c in pl_cols if not c.endswith("_MoM_%")]
    if pl_cols:
        write_time_series_sheet(
            wb, kpi_df, "PL Evolution", pl_cols, "Patrimonio Liquido - Evolucao", "area"
        )

    # Sheet 3: Quota Values
    cota_cols = [c for c in kpi_df.columns if "COTA" in c.upper() or "VALOR_COTA" in c.upper()]
    cota_cols = [c for c in cota_cols if not c.endswith("_MoM_%")]
    if cota_cols:
        write_time_series_sheet(
            wb, kpi_df, "Quota Values", cota_cols, "Valor da Cota por Classe", "line"
        )

    # Sheet 4: Monthly Returns
    rentab_cols = [c for c in kpi_df.columns if "RENTAB" in c.upper()]
    rentab_cols = [c for c in rentab_cols if not c.endswith("_MoM_%")]
    if rentab_cols:
        write_time_series_sheet(
            wb, kpi_df, "Rentabilidade", rentab_cols, "Rentabilidade Mensal (%)", "line"
        )

    # Sheet 5: Credit Rights
    dc_cols = [c for c in kpi_df.columns if "DC_" in c.upper() or "PERFORM" in c.upper()]
    dc_cols = [c for c in dc_cols if not c.endswith("_MoM_%")]
    if dc_cols:
        write_time_series_sheet(
            wb, kpi_df, "Credit Rights", dc_cols, "Direitos Creditorios", "bar"
        )

    # Sheet 6: Inadimplência
    inad_cols = [c for c in kpi_df.columns if "INADIMP" in c.upper() or "PROVIS" in c.upper() or "SUBSTIT" in c.upper()]
    inad_cols = [c for c in inad_cols if not c.endswith("_MoM_%")]
    if inad_cols:
        write_time_series_sheet(
            wb, kpi_df, "Inadimplencia", inad_cols, "Inadimplencia e Provisoes", "bar"
        )

    # Per-class sheets
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

    # Raw Data sheets
    write_raw_data_sheet(wb, tables)

    wb.save(output_path)
    print(f"\n  Report saved to: {output_path}")
