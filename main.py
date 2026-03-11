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
from src.downloader import download_monthly_zips
from src.excel_report import generate_report
from src.kpi_extractor import compute_trends, extract_kpis
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
    tables = parse_all_tables(data_dirs, cnpjs)

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

    # Step 4: Generate report
    print(f"\n[4/4] Generating Excel report...")
    generate_report(kpi_df, tables, output_path, fund_name)

    print(f"\n{'='*60}")
    print(f"  Done! Report saved to: {output_path}")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
