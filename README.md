# Facio FIDC Monitor

Automated monitoring tool for Facio's FIDC funds. Downloads monthly reports from CVM's Open Data Portal, extracts core financial KPIs, and generates Excel reports with charts.

## Monitored Fund

| Fund | CNPJ |
|------|------|
| Facio FIDC Financeiros RL | 51.119.641/0001-09 |

To add more funds, edit `config.py` and add entries to the `FUNDS` list.

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.9+.

## Usage

```bash
# Download last 12 months and generate report
python main.py

# Custom date range
python main.py --from 2024-01 --to 2025-12

# Update mode: only download new months since last run
python main.py --update

# Debug: show available CVM data columns
python main.py --discover

# Custom output path
python main.py --output /path/to/report.xlsx
```

The report is saved to `output/facio_fidc_report.xlsx` by default.

## Report Contents

The Excel report contains:

1. **Dashboard** - Summary of latest KPIs with month-over-month changes
2. **PL Evolution** - Patrimonio Liquido time series with area chart
3. **Quota Values** - Quota value per class (Senior, Mezanino, Subordinada) with line chart
4. **Credit Rights** - Performing vs non-performing credit rights with stacked bar chart
5. **Raw Data** - Full historical data tables for reference

## Core KPIs

- Patrimonio Liquido (PL) - Net assets
- Valor da Cota - Quota value per class
- Numero de Cotistas - Number of shareholders
- Direitos Creditorios - Credit rights (performing vs non-performing)
- Inadimplencia / Perdas - Default rates and losses
- Ativo Total - Total assets
- Aquisicoes / Resgates - Acquisitions and redemptions

## Scheduling (Cron)

To run automatically on the 15th of each month (after CVM's filing deadline):

```bash
# Edit crontab
crontab -e

# Add this line (adjust path):
0 20 15 * * cd /path/to/faciofidcs && python main.py --update >> /var/log/faciofidcs.log 2>&1
```

## Data Source

Data is sourced from the [CVM Open Data Portal](https://dados.cvm.gov.br/dataset/fidc-doc-inf_mensal) - structured CSV files published monthly by Brazil's securities regulator.

## Project Structure

```
faciofidcs/
├── main.py              # CLI entry point
├── config.py            # Fund CNPJs, settings, paths
├── requirements.txt     # Python dependencies
├── src/
│   ├── downloader.py    # Downloads ZIP files from CVM
│   ├── parser.py        # Parses CSVs, filters by CNPJ
│   ├── kpi_extractor.py # Computes KPIs from raw data
│   └── excel_report.py  # Generates Excel with charts
├── data/raw/            # Downloaded data (gitignored)
└── output/              # Generated reports (gitignored)
```
