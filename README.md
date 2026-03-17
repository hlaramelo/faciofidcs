# Facio FIDC Monitor

Professional monitoring dashboard for Facio's FIDC funds. Downloads monthly reports from CVM's Open Data Portal, extracts financial KPIs, and presents them in an interactive Streamlit dashboard designed for credit investors.

## Monitored Fund

| Fund | CNPJ |
|------|------|
| Facio FIDC Financeiros RL | 51.119.641/0001-09 |

To add more funds, edit `config.py` and add entries to the `FUNDS` list.

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.10+.

## Dashboard (Recommended)

```bash
streamlit run dashboard.py
```

Opens an interactive dashboard with 5 tabs:

- **Visao Geral** — KPI cards with traffic-light alerts, PL and default rate trends
- **Qualidade de Credito** — Default rate evolution, NPL breakdown, provisioning coverage
- **Subordinacao** — Credit enhancement ratios by tranche, PL composition by class
- **Performance** — Returns, quota values per class, PL evolution, quotaholder count
- **Fluxo da Carteira** — Acquisitions vs redemptions, net flow, substitutions

### Features

- Automated alert flags (default rate spikes, PL drops, low subordination)
- Interactive Plotly charts with hover details
- Date range picker in sidebar
- Raw data browser with CSV export
- Data cached for 1 hour to avoid redundant CVM downloads

## CLI (Excel Report)

The original CLI is still available for generating static Excel reports:

```bash
# Download last 12 months and generate report
python main.py

# Custom date range
python main.py --from 2024-01 --to 2025-12

# Update mode: only download new months since last run
python main.py --update

# Debug: show available CVM data columns
python main.py --discover
```

## Scheduling (Cron)

To run automatically on the 15th of each month (after CVM's filing deadline):

```bash
crontab -e

# Add this line (adjust path):
0 20 15 * * cd /path/to/faciofidcs && python main.py --update >> /var/log/faciofidcs.log 2>&1
```

## Data Source

Data is sourced from the [CVM Open Data Portal](https://dados.cvm.gov.br/dataset/fidc-doc-inf_mensal) — structured CSV files published monthly by Brazil's securities regulator.

## Project Structure

```
faciofidcs/
├── dashboard.py         # Streamlit dashboard (main entry point)
├── main.py              # CLI entry point (Excel reports)
├── config.py            # Fund CNPJs, settings, paths
├── requirements.txt     # Python dependencies
├── src/
│   ├── analytics.py     # Credit quality, subordination, flow analytics
│   ├── downloader.py    # Downloads ZIP files from CVM
│   ├── parser.py        # Parses CSVs, filters by CNPJ
│   ├── kpi_extractor.py # Computes KPIs from raw data
│   └── excel_report.py  # Generates Excel with charts
├── data/raw/            # Downloaded data (gitignored)
└── output/              # Generated reports (gitignored)
```
