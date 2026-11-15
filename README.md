# 🌐 International Cost of Capital Explorer

A Streamlit app that compares a project's **cost of equity, cost of debt and WACC in U.S. dollars and in the currency of any selected country**. Results appear side by side, along with sources, dates, verification checks and an all-industry comparison.

## What it does

- Pick an **industry** (Damodaran's U.S. industry groups) and a **target country** (54 countries that have both a Trading Economics 10Y yield and an OECD tax rate).
- Adjust the **equity risk premium** and the **target debt share** D/(D+E).
- Switch the **project tax rate** between the U.S. rate and the selected country's rate. The same rate is used for both currencies.
- **Override** any fetched input by hand: unlevered beta, U.S. and foreign corporate tax rates, USD BBB spread, and both 10-year yields.
- Optionally override the **local-currency BBB spread**. When this is off, the app shows the automatically calculated spread.
- See where each input came from, with a **date** and a status badge (🟢 live, 🟡 snapshot, ✍️ manual), plus a **🔄 Refresh all data** button.
- A **step-by-step calculation table**, **built-in verification checks**, an **all-industry comparison** (chart and table), and **CSV downloads**.

**Defaults when the app opens:** Software (System & Application), United States, U.S. tax rate, 6.5% ERP, 30% debt.

## Formulas

| Symbol | Meaning |
|---|---|
| βU | Damodaran industry **unlevered beta** |
| t | Project tax rate (OECD combined statutory CIT, U.S. or selected country) |
| w_d | Target debt share D/(D+E); D/E = w_d / (1 − w_d) |
| ERP | Equity risk premium |
| y_US, y_F | 10-year government bond yields |
| s | Damodaran Baa2/BBB default spread (USD) |

```
Levered beta        βL   = βU × [1 + (1 − t) × D/E]
USD cost of equity  Re$  = y_US + βL × ERP
USD cost of debt    Rd$  = y_US + s                      (pre-tax)
Conversion factor   k    = (1 + y_F) / (1 + y_US)
Local cost of equity Re_F = (1 + Re$) × k − 1
Local cost of debt  Rd_F = (1 + Rd$) × k − 1             (auto; implied local spread s_F = Rd_F − y_F)
                    Rd_F = y_F + s_F(manual)             (if the local spread is overridden)
WACC                     = (1 − w_d) × Re + w_d × Rd × (1 − t)
```

The yield gap stands for the expected inflation (depreciation) gap between the two currencies (relative PPP / Fisher). So with equal yields the two currencies give identical results.

## Built-in verification

The app re-runs these checks live on the current inputs:

1. **Equal government bond yields → equal results** when the local-spread override is off.
2. **Zero debt → WACC = cost of equity** in both currencies.
3. **Overriding the local spread leaves the USD results unchanged.**

## Data sources

| Input | Source | How it is fetched |
|---|---|---|
| Unlevered beta | [Damodaran betas.xls](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) | "Industry Averages" sheet, column *Unlevered beta*. Date from the "Date updated" cell |
| USD BBB spread | [Damodaran ratings](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html) | Baa2/BBB row of the *large non-financial service firms* table. Date from "Data used is as of …" |
| Corporate tax rates | [OECD Corporate Tax Statistics](https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html) | OECD SDMX API `OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT`, measure `CIT_C` (combined central + sub-central statutory rate). Latest year per country |
| 10Y government yields | [Trading Economics](https://tradingeconomics.com/bonds) | Each country's `/{country}/government-bond-yield` page (the 10Y quote and its date) |

- Live data is cached for 6 hours. **🔄 Refresh all data** clears the cache.
- If a source can't be reached, the app uses a built-in **snapshot** (captured 2026-11-15), flags it with a 🟡 badge and shows a warning.
- The Trading Economics `/bonds` overview table loads behind an AWS bot check, so the app reads only the two country pages it needs.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Requires Python 3.12.

## Deploy on Streamlit Community Cloud

1. Put `app.py`, `requirements.txt` and `README.md` at the top level of a public GitHub repo.
2. Go to [share.streamlit.io](https://share.streamlit.io), then **Create app → Yup, I have an app**.
3. Choose the repo, branch `main` and main file `app.py`. Under **Advanced settings**, pick **Python 3.12**.
4. Click **Deploy**.

## Caveats

- Betas come from U.S.-listed firms. The ERP is one mature-market premium with no separate country-risk premium.
- Sovereign 10Y yields include each government's own default risk.
- Statutory tax rates are not effective tax rates.

## Credits

Data © Aswath Damodaran (NYU Stern), OECD, Trading Economics. Flags from [flagcdn.com](https://flagcdn.com). Built with Streamlit and Plotly. Code written with Claude (Anthropic), model Claude Opus 5.5, November 2026.
