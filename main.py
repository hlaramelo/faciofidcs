#!/usr/bin/env python3
"""Facio FIDC Monitoring - CLI entry point.

Downloads monthly FIDC reports from CVM, extracts KPIs,
and generates an Excel report with charts.

Usage:
    python main.py                          # Last 12 months (default)
    python main.py --from 2024-01 --to 2025-12  # Custom date range
    python main.py --update                 # Only download new months
    python main.py --discover               # Show available columns (debug)
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path so imports work from any directory
sys.path.insert(0, str(Path(__file__).parent))

from config import DATA_DIR, DEFAULT_MONTHS_BACK, FUNDS, OUTPUT_DIR
from src.analytics import (
    compute_cdi_spread,
    compute_covenant_timeline,
    compute_credit_quality_metrics,
    compute_credit_ratios_vs_pl,
    compute_flow_metrics,
    compute_maturity_buckets,
    compute_performance_metrics,
    compute_pl_waterfall,
    compute_subordination_ratios,
    fetch_cdi_monthly,
    get_alert_flags,
)
from src.downloader import download_monthly_zips
from src.excel_report import generate_report
from src.kpi_extractor import compute_trends, extract_kpis, extract_per_class_data
from src.parser import discover_columns, parse_all_tables


def parse_month(month_str: str) -> date:
    """Parse 'YYYY-MM' string into a date (first day of month)."""
    parts = month_str.split("-")
    return date(int(parts[0]), int(parts[1]), 1)


def get_last_downloaded_month(cache_dir: Path) -> date | None:
    """Find the most recent month already downloaded."""
    if not cache_dir.exists():
        return None

    months = []
    for d in cache_dir.iterdir():
        if d.is_dir() and len(d.name) == 6 and d.name.isdigit():
            year = int(d.name[:4])
            month = int(d.name[4:])
            if 1 <= month <= 12:
                months.append(date(year, month, 1))

    return max(months) if months else None


def main():
    parser = argparse.ArgumentParser(
        description="Facio FIDC Monitoring - Download and analyze FIDC monthly reports"
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=str,
        help="Start month (YYYY-MM). Default: 12 months ago",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        type=str,
        help="End month (YYYY-MM). Default: current month",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Only download months after the last downloaded month",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Show available columns in downloaded data (debug mode)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help=f"Output file path. Default: {OUTPUT_DIR}/facio_fidc_report.xlsx",
    )

    args = parser.parse_args()

    # Determine date range
    today = date.today()
    if args.update:
        last = get_last_downloaded_month(DATA_DIR)
        if last:
            # Start from the month after the last downloaded
            if last.month == 12:
                start_date = date(last.year + 1, 1, 1)
            else:
                start_date = date(last.year, last.month + 1, 1)
            # But also re-download the full range for the report
            full_start = today - timedelta(days=DEFAULT_MONTHS_BACK * 31)
            start_date = min(start_date, full_start)
        else:
            start_date = today - timedelta(days=DEFAULT_MONTHS_BACK * 31)
        end_date = today
        print(f"Update mode: fetching {start_date.strftime('%Y-%m')} to {end_date.strftime('%Y-%m')}")
    elif args.from_date:
        start_date = parse_month(args.from_date)
        end_date = parse_month(args.to_date) if args.to_date else today
    else:
        start_date = today - timedelta(days=DEFAULT_MONTHS_BACK * 31)
        end_date = today

    output_path = Path(args.output) if args.output else OUTPUT_DIR / "facio_fidc_report.xlsx"

    # Get fund CNPJs
    cnpjs = [f["cnpj_raw"] for f in FUNDS]
    fund_name = FUNDS[0]["name"]

    print(f"\n{'='*60}")
    print(f"  Facio FIDC Monitor")
    print(f"  Fund: {fund_name}")
    print(f"  Period: {start_date.strftime('%Y-%m')} to {end_date.strftime('%Y-%m')}")
    print(f"{'='*60}\n")

    # Step 1: Download data
    print("[1/4] Downloading monthly reports from CVM...")
    data_dirs = download_monthly_zips(start_date, end_date)

    if not data_dirs:
        print("\nNo data downloaded. Check your internet connection or date range.")
        return 1

    # Step 2: Parse CSVs
    print("\n[2/4] Parsing CSV data...")
    fund_names_list = [f["name"] for f in FUNDS]
    tables = parse_all_tables(data_dirs, cnpjs, fund_names=fund_names_list)

    if not tables:
        print("\nNo data found for the specified fund(s). Verify the CNPJ in config.py.")
        print("Available CNPJs searched:", cnpjs)
        return 1

    # Debug: show available columns
    if args.discover:
        print("\n[DEBUG] Available columns per table:")
        columns = discover_columns(tables)
        for table_name, cols in columns.items():
            print(f"\n  {table_name} ({len(cols)} columns):")
            for col in cols:
                print(f"    - {col}")
        return 0

    # Step 3: Extract KPIs
    print("\n[3/4] Extracting KPIs...")
    kpi_df = extract_kpis(tables)

    if kpi_df.empty:
        print("\nCould not extract KPIs. Try --discover to see available columns.")
        return 1

    kpi_df = compute_trends(kpi_df)
    print(f"  Extracted {len(kpi_df)} monthly data points")

    # Extract per-class breakdowns
    per_class = extract_per_class_data(tables)

    # Step 4: Compute analytics
    print(f"\n[4/5] Computing analytics...")
    credit_quality = compute_credit_quality_metrics(kpi_df)
    credit_ratios_pl = compute_credit_ratios_vs_pl(kpi_df)
    flow_metrics = compute_flow_metrics(kpi_df)
    perf_metrics = compute_performance_metrics(kpi_df, per_class or {})
    sub_ratios = compute_subordination_ratios(per_class or {})
    pl_waterfall = compute_pl_waterfall(kpi_df)
    maturity_buckets = compute_maturity_buckets(tables)

    # Fetch CDI and compute spread
    cdi_df = None
    spread_metrics = pd.DataFrame()
    if not kpi_df.empty and "DT_COMPTC" in kpi_df.columns:
        min_date = pd.to_datetime(kpi_df["DT_COMPTC"]).min()
        max_date = pd.to_datetime(kpi_df["DT_COMPTC"]).max()
        if pd.notna(min_date) and pd.notna(max_date):
            cdi_start = min_date.strftime("%d/%m/%Y")
            cdi_end = max_date.strftime("%d/%m/%Y")
            print(f"  Fetching CDI data ({cdi_start} to {cdi_end})...")
            cdi_df = fetch_cdi_monthly(cdi_start, cdi_end)
            spread_metrics = compute_cdi_spread(perf_metrics, cdi_df)

    covenant_timeline = compute_covenant_timeline(kpi_df, per_class or {})
    alerts = get_alert_flags(kpi_df, per_class or {})

    analytics = {
        "credit_quality": credit_quality,
        "credit_ratios_pl": credit_ratios_pl,
        "sub_ratios": sub_ratios,
        "perf_metrics": perf_metrics,
        "spread_metrics": spread_metrics,
        "flow_metrics": flow_metrics,
        "pl_waterfall": pl_waterfall,
        "covenant_timeline": covenant_timeline,
        "maturity_buckets": maturity_buckets,
        "alerts": alerts,
    }

    # Step 5: Generate report
    print(f"\n[5/5] Generating Excel report...")
    generate_report(kpi_df, tables, output_path, fund_name, per_class, analytics)

    print(f"\n{'='*60}")
    print(f"  Done! Report saved to: {output_path}")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
