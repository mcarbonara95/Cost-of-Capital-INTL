"""
International Cost of Capital Explorer
======================================
Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country.

Data (fetched live, with a built-in snapshot as fallback):
  * Industry unlevered betas ........ Aswath Damodaran, betas.xls ("Unlevered beta")
  * USD BBB default spread .......... Damodaran, ratings.html (Baa2/BBB, large non-financial firms)
  * Corporate income tax rates ...... OECD Corporate Tax Statistics (combined statutory CIT rate)
  * 10-year government bond yields .. Trading Economics country bond pages

Built with Claude Code (Anthropic), model Claude Opus 5.5, November 2026.
"""

import io
import re
import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
URL_BETAS = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
URL_RATINGS = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html"
URL_OECD_API = ("https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,2.0/"
                ".A.CIT_C.ST.......?startPeriod={start}&dimensionAtObservation=AllDimensions")
URL_OECD_PAGE = ("https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
                 "full-report/statutory-corporate-income-tax-rates_440f9286.html")
URL_TE = "https://tradingeconomics.com/{slug}/government-bond-yield"
URL_TE_HOME = "https://tradingeconomics.com/bonds"

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")}
TTL = 6 * 3600  # cache live data for 6 hours (the Refresh button clears it)

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "USA"
DEFAULT_ERP = 6.5
DEFAULT_DEBT = 30

C_USD = "#2563EB"   # blue  = USD
C_LOC = "#DB2777"   # pink  = local currency
C_EQ = "#7C3AED"
C_DEBT = "#0EA5E9"

# ISO3 -> (name, ISO2 for flag, currency, Trading Economics slug)
COUNTRIES = {
    "USA": ("United States", "us", "USD", "united-states"),
    "GBR": ("United Kingdom", "gb", "GBP", "united-kingdom"),
    "DEU": ("Germany", "de", "EUR", "germany"),
    "FRA": ("France", "fr", "EUR", "france"),
    "ITA": ("Italy", "it", "EUR", "italy"),
    "ESP": ("Spain", "es", "EUR", "spain"),
    "PRT": ("Portugal", "pt", "EUR", "portugal"),
    "NLD": ("Netherlands", "nl", "EUR", "netherlands"),
    "BEL": ("Belgium", "be", "EUR", "belgium"),
    "AUT": ("Austria", "at", "EUR", "austria"),
    "IRL": ("Ireland", "ie", "EUR", "ireland"),
    "FIN": ("Finland", "fi", "EUR", "finland"),
    "GRC": ("Greece", "gr", "EUR", "greece"),
    "HRV": ("Croatia", "hr", "EUR", "croatia"),
    "SVK": ("Slovakia", "sk", "EUR", "slovakia"),
    "SVN": ("Slovenia", "si", "EUR", "slovenia"),
    "LTU": ("Lithuania", "lt", "EUR", "lithuania"),
    "BGR": ("Bulgaria", "bg", "EUR", "bulgaria"),
    "CHE": ("Switzerland", "ch", "CHF", "switzerland"),
    "SWE": ("Sweden", "se", "SEK", "sweden"),
    "NOR": ("Norway", "no", "NOK", "norway"),
    "DNK": ("Denmark", "dk", "DKK", "denmark"),
    "ISL": ("Iceland", "is", "ISK", "iceland"),
    "POL": ("Poland", "pl", "PLN", "poland"),
    "CZE": ("Czech Republic", "cz", "CZK", "czech-republic"),
    "HUN": ("Hungary", "hu", "HUF", "hungary"),
    "ROU": ("Romania", "ro", "RON", "romania"),
    "TUR": ("Turkey", "tr", "TRY", "turkey"),
    "ISR": ("Israel", "il", "ILS", "israel"),
    "JPN": ("Japan", "jp", "JPY", "japan"),
    "CHN": ("China", "cn", "CNY", "china"),
    "HKG": ("Hong Kong", "hk", "HKD", "hong-kong"),
    "KOR": ("South Korea", "kr", "KRW", "south-korea"),
    "SGP": ("Singapore", "sg", "SGD", "singapore"),
    "IND": ("India", "in", "INR", "india"),
    "IDN": ("Indonesia", "id", "IDR", "indonesia"),
    "MYS": ("Malaysia", "my", "MYR", "malaysia"),
    "THA": ("Thailand", "th", "THB", "thailand"),
    "PHL": ("Philippines", "ph", "PHP", "philippines"),
    "VNM": ("Vietnam", "vn", "VND", "vietnam"),
    "PAK": ("Pakistan", "pk", "PKR", "pakistan"),
    "AUS": ("Australia", "au", "AUD", "australia"),
    "NZL": ("New Zealand", "nz", "NZD", "new-zealand"),
    "CAN": ("Canada", "ca", "CAD", "canada"),
    "MEX": ("Mexico", "mx", "MXN", "mexico"),
    "BRA": ("Brazil", "br", "BRL", "brazil"),
    "CHL": ("Chile", "cl", "CLP", "chile"),
    "COL": ("Colombia", "co", "COP", "colombia"),
    "PER": ("Peru", "pe", "PEN", "peru"),
    "ZAF": ("South Africa", "za", "ZAR", "south-africa"),
    "NGA": ("Nigeria", "ng", "NGN", "nigeria"),
    "KEN": ("Kenya", "ke", "KES", "kenya"),
    "QAT": ("Qatar", "qa", "QAR", "qatar"),
    "ZMB": ("Zambia", "zm", "ZMW", "zambia"),
}

# --------------------------------------------------------------------------
# Built-in snapshot (used only if a live source cannot be reached).
# Captured 2026-11-15 from the same sources.
# --------------------------------------------------------------------------
SNAP_DATE = "2026-11-15"
SNAP_BETAS_DATE = "2026-01-05"
SNAP_BBB = 1.11
SNAP_BBB_DATE = "January 2026"
SNAP_YIELD_YEAR = 2026
SNAP_BETAS = {'Advertising': 0.930086,
 'Aerospace/Defense': 0.846669,
 'Air Transport': 0.70405,
 'Apparel': 0.757982,
 'Auto & Truck': 1.269033,
 'Auto Parts': 1.021714,
 'Bank (Money Center)': 0.341059,
 'Banks (Regional)': 0.286516,
 'Beverage (Alcoholic)': 0.613172,
 'Beverage (Soft)': 0.555671,
 'Broadcasting': 0.286362,
 'Brokerage & Investment Banking': 0.580849,
 'Building Materials': 0.930162,
 'Business & Consumer Services': 0.773588,
 'Cable TV': 0.352392,
 'Chemical (Basic)': 0.580033,
 'Chemical (Diversified)': 0.366552,
 'Chemical (Specialty)': 0.792227,
 'Coal & Related Energy': 1.016535,
 'Computer Services': 0.91551,
 'Computers/Peripherals': 1.305062,
 'Construction Supplies': 1.016068,
 'Diversified': 0.78893,
 'Drugs (Biotechnology)': 1.034129,
 'Drugs (Pharmaceutical)': 0.886211,
 'Education': 0.660196,
 'Electrical Equipment': 1.147795,
 'Electronics (Consumer & Office)': 0.829853,
 'Electronics (General)': 0.897365,
 'Engineering/Construction': 1.094912,
 'Entertainment': 0.737184,
 'Environmental & Waste Services': 0.814469,
 'Farming/Agriculture': 0.81302,
 'Financial Svcs. (Non-bank & Insurance)': 0.318882,
 'Food Processing': 0.457418,
 'Food Wholesalers': 0.640882,
 'Furn/Home Furnishings': 0.624788,
 'Green & Renewable Energy': 0.463301,
 'Healthcare Products': 0.829063,
 'Healthcare Support Services': 0.688916,
 'Heathcare Information and Technology': 0.991301,
 'Homebuilding': 0.78496,
 'Hospitals/Healthcare Facilities': 0.55173,
 'Hotel/Gaming': 0.832251,
 'Household Products': 0.717816,
 'Information Services': 0.737177,
 'Insurance (General)': 0.56364,
 'Insurance (Life)': 0.427156,
 'Insurance (Prop/Cas.)': 0.435656,
 'Investments & Asset Management': 0.529716,
 'Machinery': 0.867976,
 'Metals & Mining': 0.963643,
 'Office Equipment & Services': 0.980604,
 'Oil/Gas (Integrated)': 0.271219,
 'Oil/Gas (Production and Exploration)': 0.56276,
 'Oil/Gas Distribution': 0.465076,
 'Oilfield Svcs/Equip.': 0.743039,
 'Packaging & Container': 0.723069,
 'Paper/Forest Products': 0.721553,
 'Power': 0.310024,
 'Precious Metals': 0.793243,
 'Publishing & Newspapers': 0.477307,
 'R.E.I.T.': 0.392904,
 'Real Estate (Development)': 0.478288,
 'Real Estate (General/Diversified)': 0.577859,
 'Real Estate (Operations & Services)': 0.814892,
 'Recreation': 0.695091,
 'Reinsurance': 0.438409,
 'Restaurant/Dining': 0.76742,
 'Retail (Automotive)': 0.698433,
 'Retail (Building Supply)': 1.307014,
 'Retail (Distributors)': 0.782683,
 'Retail (General)': 0.759964,
 'Retail (Grocery and Food)': 0.804751,
 'Retail (REITs)': 0.436173,
 'Retail (Special Lines)': 0.948783,
 'Rubber& Tires': 0.143534,
 'Semiconductor': 1.489258,
 'Semiconductor Equip': 1.348073,
 'Shipbuilding & Marine': 0.644013,
 'Shoe': 0.933675,
 'Software (Entertainment)': 1.012781,
 'Software (Internet)': 1.546064,
 'Software (System & Application)': 1.225392,
 'Steel': 0.903514,
 'Telecom (Wireless)': 0.387259,
 'Telecom. Equipment': 0.863491,
 'Telecom. Services': 0.365434,
 'Tobacco': 0.67759,
 'Transportation': 0.675311,
 'Transportation (Railroads)': 0.806948,
 'Trucking': 0.850418,
 'Utility (General)': 0.148613,
 'Utility (Water)': 0.281177,
 'Total Market': 0.72173,
 'Total Market (without financials)': 0.877517}
SNAP_YIELDS = {'USA': (5.145, 'Nov/13'),
 'GBR': (5.3377, 'Nov/13'),
 'DEU': (3.3762, 'Nov/13'),
 'FRA': (4.921, 'Nov/13'),
 'ITA': (4.437, 'Nov/13'),
 'ESP': (3.9442, 'Nov/13'),
 'PRT': (3.8186, 'Nov/13'),
 'NLD': (3.4768, 'Nov/13'),
 'BEL': (4.3545, 'Nov/13'),
 'AUT': (3.6096, 'Nov/13'),
 'IRL': (3.5391, 'Nov/13'),
 'FIN': (3.7611, 'Nov/13'),
 'GRC': (4.2636, 'Nov/13'),
 'CHE': (0.5626, 'Nov/13'),
 'SWE': (3.098, 'Nov/13'),
 'NOR': (4.3842, 'Nov/13'),
 'DNK': (3.1693, 'Nov/13'),
 'ISL': (6.81, 'Nov/13'),
 'POL': (6.335, 'Nov/13'),
 'CZE': (5.2222, 'Nov/13'),
 'HUN': (5.5249, 'Nov/13'),
 'ROU': (7.12, 'Nov/13'),
 'BGR': (3.63, None),
 'HRV': (3.8668, 'Nov/13'),
 'SVK': (4.305, 'Nov/13'),
 'SVN': (3.914, 'Nov/13'),
 'LTU': (4.327, 'Nov/13'),
 'TUR': (33.52, 'Nov/13'),
 'ISR': (4.183, 'Nov/13'),
 'JPN': (2.8616, 'Nov/13'),
 'CHN': (1.6181, 'Nov/13'),
 'HKG': (3.994, 'Nov/13'),
 'KOR': (3.987, 'Nov/13'),
 'SGP': (2.3296, 'Nov/13'),
 'IND': (7.312, 'Nov/13'),
 'IDN': (7.607, 'Nov/13'),
 'MYS': (3.8628, 'Nov/13'),
 'THA': (1.995, 'Nov/13'),
 'PHL': (7.767, 'Nov/13'),
 'VNM': (4.5726, 'Nov/13'),
 'PAK': (12.604, 'Nov/13'),
 'AUS': (5.129, 'Nov/13'),
 'NZL': (4.7462, 'Nov/13'),
 'CAN': (3.856, 'Nov/13'),
 'MEX': (9.308, 'Nov/13'),
 'BRA': (15.335, 'Nov/13'),
 'CHL': (6.01, 'Nov/13'),
 'COL': (12.698, 'Nov/13'),
 'PER': (6.26, None),
 'ZAF': (8.675, 'Nov/13'),
 'NGA': (16.598, 'Nov/13'),
 'KEN': (12.5, 'Nov/13'),
 'QAT': (4.03, None),
 'ZMB': (14.74, 'Nov/13')}
SNAP_TAX = {'USA': (2026, 25.5285),
 'GBR': (2026, 25.0),
 'DEU': (2026, 30.133),
 'FRA': (2026, 36.13),
 'ITA': (2026, 27.81),
 'ESP': (2026, 25.0),
 'PRT': (2026, 29.5),
 'NLD': (2026, 25.8),
 'BEL': (2026, 25.0),
 'AUT': (2026, 23.0),
 'IRL': (2026, 12.5),
 'FIN': (2026, 20.0),
 'GRC': (2026, 22.0),
 'CHE': (2026, 19.4719),
 'SWE': (2026, 20.6),
 'NOR': (2026, 22.0),
 'DNK': (2026, 22.0),
 'ISL': (2026, 20.0),
 'POL': (2026, 19.0),
 'CZE': (2026, 21.0),
 'HUN': (2026, 9.0),
 'ROU': (2026, 16.0),
 'BGR': (2026, 10.0),
 'HRV': (2026, 18.0),
 'SVK': (2026, 24.0),
 'SVN': (2026, 22.0),
 'LTU': (2026, 17.0),
 'TUR': (2025, 25.0),
 'ISR': (2025, 23.0),
 'JPN': (2026, 29.74),
 'CHN': (2026, 25.0),
 'HKG': (2026, 16.5),
 'KOR': (2026, 27.5),
 'SGP': (2026, 17.0),
 'IND': (2026, 25.17),
 'IDN': (2026, 22.0),
 'MYS': (2026, 24.0),
 'THA': (2026, 20.0),
 'PHL': (2026, 25.0),
 'VNM': (2026, 20.0),
 'PAK': (2026, 29.0),
 'AUS': (2026, 30.0),
 'NZL': (2026, 28.0),
 'CAN': (2026, 26.0),
 'MEX': (2026, 30.0),
 'BRA': (2026, 34.0),
 'CHL': (2026, 27.0),
 'COL': (2025, 35.0),
 'PER': (2026, 29.5),
 'ZAF': (2026, 27.0),
 'NGA': (2026, 30.0),
 'KEN': (2026, 30.0),
 'QAT': (2026, 10.0),
 'ZMB': (2026, 30.0)}


# --------------------------------------------------------------------------
# The cost-of-capital engine (pure functions — easy to verify by hand)
# --------------------------------------------------------------------------
def levered_beta(bu, t, wd):
    """Hamada: βL = βU × [1 + (1 − t) × D/E], with D/E = wd / (1 − wd)."""
    de = wd / (1.0 - wd)
    return bu * (1.0 + (1.0 - t) * de)


def engine(bu, t, wd, erp, y_us, y_f, s_usd, s_f_override=None):
    """All rates are decimals (0.05 = 5%). `bu` may be a scalar or a numpy array.

    USD:    Re$ = y_US + βL·ERP ;  Rd$ = y_US + s_USD
    Local:  R_F = (1 + R$)·(1 + y_F)/(1 + y_US) − 1     (yield-differential conversion)
            Rd_F = y_F + s_F  when the local spread is overridden
    WACC  = (1 − wd)·Re + wd·Rd·(1 − t)
    """
    bl = levered_beta(bu, t, wd)
    k = (1.0 + y_f) / (1.0 + y_us)                     # currency conversion factor

    re_usd = y_us + bl * erp
    rd_usd = y_us + s_usd
    re_loc = (1.0 + re_usd) * k - 1.0

    s_f_auto = (1.0 + rd_usd) * k - 1.0 - y_f          # implied local BBB spread
    s_f = s_f_auto if s_f_override is None else s_f_override
    rd_loc = y_f + s_f

    def wacc(re, rd):
        return (1.0 - wd) * re + wd * rd * (1.0 - t)

    return {
        "beta_u": bu, "beta_l": bl, "de": wd / (1.0 - wd), "k": k,
        "usd": {"rf": y_us, "spread": s_usd, "re": re_usd, "rd_pre": rd_usd,
                "rd_after": rd_usd * (1.0 - t), "wacc": wacc(re_usd, rd_usd)},
        "loc": {"rf": y_f, "spread": s_f, "spread_auto": s_f_auto, "re": re_loc,
                "rd_pre": rd_loc, "rd_after": rd_loc * (1.0 - t), "wacc": wacc(re_loc, rd_loc)},
    }


# --------------------------------------------------------------------------
# Live data fetchers. Each `_live_*` raises on failure (exceptions are not
# cached), and the public wrapper falls back to the snapshot.
# --------------------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _get(url, **kw):
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=kw.pop("timeout", 25), **kw)
    r.raise_for_status()
    return r


@st.cache_data(ttl=TTL, show_spinner=False)
def _live_betas():
    raw = pd.read_excel(io.BytesIO(_get(URL_BETAS).content), sheet_name="Industry Averages",
                        header=None, engine="xlrd")
    hdr = raw.index[raw[0].astype(str).str.strip() == "Industry Name"][0]
    cols = [str(c).strip() for c in raw.iloc[hdr]]
    col_bu = cols.index("Unlevered beta")
    body = raw.iloc[hdr + 1:].dropna(subset=[0])
    betas = {str(r[0]).strip(): float(r[col_bu]) for _, r in body.iterrows()
             if pd.notna(r[col_bu])}
    updated = raw.iloc[0, 1]
    updated = pd.Timestamp(updated).strftime("%Y-%m-%d") if pd.notna(updated) else "n/a"
    if len(betas) < 50:
        raise ValueError("unexpected betas.xls layout")
    return betas, updated, _now()


@st.cache_data(ttl=TTL, show_spinner=False)
def _live_bbb():
    html = _get(URL_RATINGS).content.decode("latin-1")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&nbsp;", " ")
    # first Baa2/BBB row = the "large non-financial service firms" table (left side)
    m = re.search(r"Baa2/BBB\s+([\d.]+)\s*%", text)
    if not m:
        raise ValueError("Baa2/BBB row not found")
    d = re.search(r"as of\s+([A-Z][a-z]+\s+\d{4})", text)
    return float(m.group(1)), (d.group(1) if d else "n/a"), _now()


@st.cache_data(ttl=TTL, show_spinner=False)
def _live_tax():
    url = URL_OECD_API.format(start=date.today().year - 5)
    r = _get(url, headers={"Accept": "application/vnd.sdmx.data+csv; charset=utf-8; version=2"},
             timeout=40)
    df = pd.read_csv(io.StringIO(r.text)).dropna(subset=["OBS_VALUE"])
    df = df.sort_values("TIME_PERIOD").groupby("REF_AREA").last()
    out = {iso: (int(row["TIME_PERIOD"]), float(row["OBS_VALUE"])) for iso, row in df.iterrows()}
    if "USA" not in out:
        raise ValueError("OECD response missing USA")
    return out, _now()


def _infer_quote_date(md):
    """Trading Economics shows 'Nov/13' — add the year (last year if that date is in the future)."""
    if not md:
        return None
    try:
        d = datetime.strptime(f"{md}/{date.today().year}", "%b/%d/%Y").date()
        if d > date.today():
            d = d.replace(year=d.year - 1)
        return d.isoformat()
    except ValueError:
        return None


@st.cache_data(ttl=TTL, show_spinner=False)
def _live_yield(slug):
    html = _get(URL_TE.format(slug=slug)).text
    val = None
    meta = re.search(r"TEChartsMeta\s*=\s*(\[.*?\]);", html, re.S)
    if meta:
        j = json.loads(meta.group(1))[0]
        if "10Y" in (j.get("name") or "") or "10" in (j.get("symbol") or ""):
            val = j.get("last")
    row = re.search(r'<tr[^>]*data-symbol="([^"]+)"[^>]*>(.*?)</tr>', html, re.S)
    qdate = None
    if row:
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", row.group(2))).strip()
        if val is None:
            m = re.search(r"10Y\s+(-?[\d.]+)", txt)
            val = float(m.group(1)) if m else None
        d = re.search(r"([A-Z][a-z]{2}/\d{1,2})\s*$", txt)
        qdate = _infer_quote_date(d.group(1)) if d else None
    if val is None:
        raise ValueError("10Y yield not found on page")
    return float(val), qdate, _now()


# Public wrappers → (value, meta dict)
def get_betas():
    try:
        b, upd, at = _live_betas()
        return b, {"status": "live", "as_of": upd, "fetched": at}
    except Exception as e:
        return SNAP_BETAS, {"status": "snapshot", "as_of": SNAP_BETAS_DATE, "fetched": SNAP_DATE, "err": str(e)}


def get_bbb():
    try:
        v, d, at = _live_bbb()
        return v, {"status": "live", "as_of": d, "fetched": at}
    except Exception as e:
        return SNAP_BBB, {"status": "snapshot", "as_of": SNAP_BBB_DATE, "fetched": SNAP_DATE, "err": str(e)}


def get_tax():
    try:
        t, at = _live_tax()
        return t, {"status": "live", "fetched": at}
    except Exception as e:
        return SNAP_TAX, {"status": "snapshot", "fetched": SNAP_DATE, "err": str(e)}


def get_yield(iso):
    try:
        v, d, at = _live_yield(COUNTRIES[iso][3])
        return v, {"status": "live", "as_of": d or "latest quote", "fetched": at}
    except Exception as e:
        v, md = SNAP_YIELDS[iso]
        d = f"{SNAP_YIELD_YEAR}-{datetime.strptime(md, '%b/%d').strftime('%m-%d')}" if md else "n/a"
        return v, {"status": "snapshot", "as_of": d, "fetched": SNAP_DATE, "err": str(e)}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def pct(x, d=2):
    return f"{x * 100:.{d}f}%"


def pp(x, d=2):
    return f"{x * 100:+.{d}f} pp"


def flag_img(iso, h=46):
    return (f'<img src="https://flagcdn.com/w160/{COUNTRIES[iso][1]}.png" '
            f'style="height:{h}px" alt="{COUNTRIES[iso][0]} flag">')


def badge(status):
    return {"live": '<span class="badge live">● LIVE</span>',
            "snapshot": '<span class="badge snap">● SNAPSHOT</span>',
            "manual": '<span class="badge man">✍ MANUAL</span>'}[status]


# --------------------------------------------------------------------------
# Page + styling
# --------------------------------------------------------------------------
st.set_page_config(page_title="International Cost of Capital", page_icon="🌐", layout="wide")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&display=swap');
h1, h2, h3, .hero h1, .card .big, .tile .val { font-family: 'Space Grotesk', sans-serif !important; }
.block-container { padding-top: 1.6rem; }
.hero { background: linear-gradient(120deg, #0F766E 0%, #2563EB 45%, #DB2777 100%);
  border-radius: 22px; padding: 26px 30px; color: #fff; margin-bottom: 18px;
  box-shadow: 0 12px 30px rgba(37,99,235,.30); position: relative; overflow: hidden; }
.hero:after { content: "🌐"; position: absolute; right: 24px; top: 4px; font-size: 110px; opacity: .14; }
.hero h1 { color: #fff; margin: 0 0 4px 0; font-size: 2.1rem; }
.hero p { margin: 0; opacity: .93; font-size: 1.02rem; }
.flags { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; flex-wrap: wrap; }
.flags img { border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,.30); border: 2px solid rgba(255,255,255,.85); }
.flags .pair { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.5rem; }
.flags .arrow { font-size: 1.6rem; opacity: .9; }
.card { border-radius: 20px; padding: 20px 22px; color: #fff; box-shadow: 0 10px 24px rgba(0,0,0,.18); }
.card.usd { background: linear-gradient(135deg, #1E3A8A, #2563EB); }
.card.loc { background: linear-gradient(135deg, #9D174D, #DB2777); }
.card .head { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.card .head img { border-radius: 6px; border: 2px solid rgba(255,255,255,.8); }
.card .ccy { font-family: 'Space Grotesk', sans-serif; font-size: 1.35rem; font-weight: 700; }
.card .tag { display: inline-block; background: rgba(255,255,255,.22); padding: 3px 11px;
  border-radius: 999px; font-weight: 700; letter-spacing: .08em; font-size: .75rem; }
.card .big { font-size: 3rem; font-weight: 700; line-height: 1.05; margin: 8px 0 2px 0; }
.card .biglab { font-size: .85rem; opacity: .9; text-transform: uppercase; letter-spacing: .08em; }
.card table { width: 100%; margin-top: 12px; border-collapse: collapse; color: #fff; }
.card td { padding: 5px 2px; border-top: 1px solid rgba(255,255,255,.22); font-size: .95rem; }
.card td.v { text-align: right; font-family: 'Space Grotesk', sans-serif; font-weight: 600; }
.gap { border-radius: 16px; padding: 14px 18px; margin-top: 14px;
  border: 1px dashed rgba(128,128,128,.5); background: rgba(219,39,119,.06); }
[class*="st-key-src_"] { border-radius: 16px; padding: 12px 14px 8px 14px; gap: .15rem;
  border: 1px solid rgba(128,128,128,.25); background: rgba(37,99,235,.05); }
.tile .lab { font-size: .74rem; text-transform: uppercase; letter-spacing: .07em; opacity: .72; }
.tile .val { font-size: 1.45rem; font-weight: 700; }
.tile .note { font-size: .78rem; opacity: .75; line-height: 1.35; }
.badge { display: inline-block; font-size: .66rem; font-weight: 700; letter-spacing: .06em;
  padding: 1px 8px; border-radius: 999px; margin-left: 4px; vertical-align: middle; }
.badge.live { background: #DCFCE7; color: #166534; }
.badge.snap { background: #FEF3C7; color: #92400E; }
.badge.man  { background: #EDE9FE; color: #5B21B6; }
.check { border-radius: 14px; padding: 10px 14px; margin-bottom: 8px; border: 1px solid rgba(128,128,128,.25); }
.check.ok { background: rgba(22,163,74,.08); } .check.bad { background: rgba(220,38,38,.10); }
</style>
""",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
with st.spinner("Fetching betas, spreads and tax rates…"):
    BETAS, m_beta = get_betas()
    BBB, m_bbb = get_bbb()
    TAX, m_tax = get_tax()

industries = list(BETAS.keys())
codes = [c for c in COUNTRIES if c in TAX or c in SNAP_TAX]

# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
if "industry" not in st.session_state or st.session_state.industry not in industries:
    st.session_state.industry = DEFAULT_INDUSTRY if DEFAULT_INDUSTRY in industries else industries[0]
if "country" not in st.session_state:
    st.session_state.country = DEFAULT_COUNTRY


def _reset():
    st.session_state.clear()


with st.sidebar:
    st.markdown("## 🏗️ Project setup")
    st.selectbox("Industry (Damodaran, US firms)", industries, key="industry")
    st.selectbox("Target country", codes, key="country",
                 format_func=lambda c: f"{COUNTRIES[c][0]} · {COUNTRIES[c][2]}")
    erp = st.slider("Equity risk premium (%)", 2.0, 12.0, DEFAULT_ERP, 0.1, key="erp") / 100
    wd = st.slider("Target debt share D/(D+E) (%)", 0, 90, DEFAULT_DEBT, 1, key="wd") / 100

    st.markdown("**🧾 Project tax rate**")
    tax_choice = st.segmented_control(
        "Project tax rate", ["🇺🇸 U.S. rate", "🌍 Selected-country rate"],
        default="🇺🇸 U.S. rate", key="tax_choice", label_visibility="collapsed",
        help="The same tax rate is used for both currencies (re-levering beta and the debt tax shield).")
    if tax_choice is None:
        tax_choice = "🇺🇸 U.S. rate"

    st.markdown("---")
    st.markdown("## ✍️ Manual overrides")
    st.caption("Switch on to replace a fetched value. Values are in % (beta is a number).")

iso = st.session_state.country
name_f, iso2_f, ccy_f, _ = COUNTRIES[iso]
industry = st.session_state.industry

with st.spinner(f"Fetching 10-year yields for the U.S. and {name_f}…"):
    Y_US, m_yus = get_yield("USA")
    Y_F, m_yf = (Y_US, dict(m_yus)) if iso == "USA" else get_yield(iso)

tax_us_fetched = TAX.get("USA", SNAP_TAX["USA"])
tax_f_fetched = TAX.get(iso, SNAP_TAX.get(iso))


def override(label, fetched, key, step=0.01, fmt="%.4f", help=None):
    """Toggle + number input. Returns (value_used, is_manual)."""
    on = st.toggle(label, key=f"on_{key}", help=help)
    if on:
        v = st.number_input(f"{label} — manual", value=float(fetched), step=step, format=fmt,
                            key=f"val_{key}", label_visibility="collapsed")
        return v, True
    st.caption(f"↳ using fetched: **{fmt % fetched}**")
    return fetched, False


with st.sidebar:
    bu, man_bu = override("Unlevered beta", BETAS[industry], f"bu_{industry}", 0.01, "%.4f")
    t_us_pct, man_tus = override("U.S. corporate tax rate (%)", tax_us_fetched[1], "tax_USA", 0.1, "%.2f")
    if iso != "USA":
        t_f_pct, man_tf = override(f"{name_f} corporate tax rate (%)", tax_f_fetched[1], f"ftax_{iso}", 0.1, "%.2f")
    s_usd_pct, man_s = override("USD BBB spread (%)", BBB, "s_usd", 0.01, "%.2f")
    y_us_pct, man_yus = override("U.S. 10Y yield (%)", Y_US, "y_USA", 0.01, "%.3f")
    if iso != "USA":
        y_f_pct, man_yf = override(f"{name_f} 10Y yield (%)", Y_F, f"fy_{iso}", 0.01, "%.3f")
    else:  # selected country is the U.S. itself → foreign inputs mirror the U.S. ones
        t_f_pct, man_tf, y_f_pct, man_yf = t_us_pct, man_tus, y_us_pct, man_yus

    # foreign-currency BBB spread: the auto value depends on the inputs above
    _auto = engine(bu, (t_us_pct if tax_choice.startswith("🇺🇸") else t_f_pct) / 100, wd, erp,
                   y_us_pct / 100, y_f_pct / 100, s_usd_pct / 100)["loc"]["spread_auto"] * 100
    on_sf = st.toggle(f"{ccy_f} BBB spread (%)", key=f"on_sf_{iso}",
                      help="Off = auto: the USD pre-tax cost of debt converted into local currency, minus the local 10Y yield.")
    if on_sf:
        s_f_pct = st.number_input(f"{ccy_f} BBB spread — manual", value=round(_auto, 4), step=0.01,
                                  format="%.3f", key=f"val_sf_{iso}", label_visibility="collapsed")
    else:
        s_f_pct = None
        st.caption(f"↳ auto-calculated: **{_auto:.3f}%**")

    st.markdown("---")
    if st.button("🔄 Refresh all data", width="stretch", type="primary"):
        st.cache_data.clear()
        st.rerun()
    st.button("↺ Reset to defaults", width="stretch", on_click=_reset)

t_proj = (t_us_pct if tax_choice.startswith("🇺🇸") else t_f_pct) / 100
tax_src = "U.S." if tax_choice.startswith("🇺🇸") else name_f
y_us, y_f, s_usd = y_us_pct / 100, y_f_pct / 100, s_usd_pct / 100
s_f = None if s_f_pct is None else s_f_pct / 100

R = engine(bu, t_proj, wd, erp, y_us, y_f, s_usd, s_f)
U, L = R["usd"], R["loc"]

# --------------------------------------------------------------------------
# Hero
# --------------------------------------------------------------------------
st.markdown(
    f'<div class="hero"><div class="flags">{flag_img("USA")}<span class="pair">USD</span>'
    f'<span class="arrow">⇄</span>{flag_img(iso)}<span class="pair">{ccy_f}</span></div>'
    f'<h1>International Cost of Capital</h1>'
    f'<p><b>{industry}</b> project · {name_f} · ERP {erp * 100:.1f}% · debt {wd * 100:.0f}% · '
    f'{tax_src} tax rate {pct(t_proj)}</p></div>',
    unsafe_allow_html=True,
)

if iso == "USA":
    st.info("🇺🇸 United States is selected, so both columns are in USD and match exactly. "
            "Pick a target country in the sidebar to see the currency effect.", icon="💡")

# --------------------------------------------------------------------------
# Results side by side
# --------------------------------------------------------------------------
def card(cls, flag_iso, ccy, res, extra_spread_note):
    rows = [
        ("Risk-free rate (10Y govt)", pct(res["rf"])),
        ("Levered beta βL", f"{R['beta_l']:.3f}"),
        ("Cost of equity", pct(res["re"])),
        (f"BBB spread {extra_spread_note}", pct(res["spread"])),
        ("Pre-tax cost of debt", pct(res["rd_pre"])),
        (f"After-tax cost of debt (t = {pct(t_proj, 1)})", pct(res["rd_after"])),
        ("Equity / Debt weights", f"{(1 - wd) * 100:.0f}% / {wd * 100:.0f}%"),
    ]
    trs = "".join(f"<tr><td>{a}</td><td class='v'>{b}</td></tr>" for a, b in rows)
    return (f'<div class="card {cls}"><div class="head">{flag_img(flag_iso, 34)}'
            f'<span class="ccy">{ccy}</span><span class="tag">{"USD" if cls == "usd" else "LOCAL CURRENCY"}</span></div>'
            f'<div class="biglab">WACC</div><div class="big">{pct(res["wacc"])}</div>'
            f'<div class="biglab">Cost of equity {pct(res["re"])}</div><table>{trs}</table></div>')


sf_note = "(manual)" if s_f is not None else "(auto)"
c1, c2 = st.columns(2, gap="medium")
c1.markdown(card("usd", "USA", "U.S. dollar", U, "(Damodaran)"), unsafe_allow_html=True)
c2.markdown(card("loc", iso, f"{name_f} · {ccy_f}", L, sf_note), unsafe_allow_html=True)

st.markdown(
    f'<div class="gap">🔁 <b>{ccy_f} − USD gap:</b> cost of equity {pp(L["re"] - U["re"])}, '
    f'WACC {pp(L["wacc"] - U["wacc"])} &nbsp;·&nbsp; 10Y yield gap {pp(y_f - y_us)} '
    f'&nbsp;·&nbsp; conversion factor (1+y<sub>F</sub>)/(1+y<sub>US</sub>) = <b>{R["k"]:.5f}</b></div>',
    unsafe_allow_html=True,
)

# Comparison chart
st.markdown("### 📊 Side by side")
labels = ["Cost of equity", "Pre-tax cost of debt", "After-tax cost of debt", "WACC"]
keys = ["re", "rd_pre", "rd_after", "wacc"]
fig = go.Figure()
for nm, res, col in [("USD", U, C_USD), (ccy_f, L, C_LOC)]:
    vals = [res[k] * 100 for k in keys]
    fig.add_bar(name=nm, x=labels, y=vals, marker_color=col,
                text=[f"{v:.2f}%" for v in vals], textposition="outside",
                hovertemplate="%{x}<br>" + nm + ": %{y:.3f}%<extra></extra>")
fig.update_layout(barmode="group", height=380, margin=dict(l=10, r=10, t=30, b=10),
                  yaxis_title="% per year", legend=dict(orientation="h", y=1.12, x=0),
                  bargap=0.25)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# --------------------------------------------------------------------------
# Data sources
# --------------------------------------------------------------------------
st.markdown("### 🛰️ Inputs, sources & dates")
_tax_f_year = tax_f_fetched[0]
tiles = [
    ("Unlevered beta", f"{bu:.4f}", "manual" if man_bu else m_beta["status"],
     f'<a href="{URL_BETAS}">Damodaran betas.xls</a> · {industry}<br>updated {m_beta["as_of"]}'),
    ("USD BBB spread", f"{s_usd_pct:.2f}%", "manual" if man_s else m_bbb["status"],
     f'<a href="{URL_RATINGS}">Damodaran ratings</a> · Baa2/BBB, large non-financial<br>data as of {m_bbb["as_of"]}'),
    ("U.S. tax rate", f"{t_us_pct:.2f}%", "manual" if man_tus else m_tax["status"],
     f'<a href="{URL_OECD_PAGE}">OECD</a> combined statutory CIT<br>year {tax_us_fetched[0]}'),
    (f"{name_f} tax rate", f"{t_f_pct:.2f}%", "manual" if man_tf else m_tax["status"],
     f'<a href="{URL_OECD_PAGE}">OECD</a> combined statutory CIT<br>year {_tax_f_year}'),
    ("U.S. 10Y yield", f"{y_us_pct:.3f}%", "manual" if man_yus else m_yus["status"],
     f'<a href="{URL_TE.format(slug="united-states")}">Trading Economics</a><br>quote {m_yus["as_of"]}'),
    (f"{name_f} 10Y yield", f"{y_f_pct:.3f}%", "manual" if man_yf else m_yf["status"],
     f'<a href="{URL_TE.format(slug=COUNTRIES[iso][3])}">Trading Economics</a><br>quote {m_yf["as_of"]}'),
]
cols = st.columns(3)
for i, (lab, val, status, note) in enumerate(tiles):
    with cols[i % 3].container(key=f"src_{i}"):
        st.markdown(f'<div class="tile"><div class="lab">{lab} {badge(status)}</div>'
                    f'<div class="val">{val}</div><div class="note">{note}</div></div>',
                    unsafe_allow_html=True)

fetched = sorted({m.get("fetched", "") for m in (m_beta, m_bbb, m_tax, m_yus, m_yf)})
st.caption(f"Last fetched: {', '.join(fetched)}. Live data is cached for 6 hours. "
           "Press **🔄 Refresh all data** in the sidebar to fetch again.")
errs = {k: m["err"] for k, m in [("betas", m_beta), ("BBB spread", m_bbb), ("tax rates", m_tax),
                                  ("U.S. yield", m_yus), (f"{name_f} yield", m_yf)]
        if "err" in m and not (iso == "USA" and m is m_yf)}
if errs:
    st.warning("⚠️ Some live sources could not be reached, so the built-in snapshot from "
               f"{SNAP_DATE} is used for: **{', '.join(errs)}**. You can also type values in the sidebar overrides.")
    with st.expander("Error details"):
        st.json(errs)

# --------------------------------------------------------------------------
# Step-by-step calculation
# --------------------------------------------------------------------------
st.markdown("### 🧮 Step by step")
de = R["de"]
k = R["k"]
steps = [
    ("D/E", "w_d / (1 − w_d)", f"{wd:.4f} / {1 - wd:.4f}", f"{de:.4f}", f"{de:.4f}"),
    ("Levered beta βL", "βU × [1 + (1 − t)·D/E]", f"{bu:.4f} × [1 + {1 - t_proj:.4f} × {de:.4f}]",
     f"{R['beta_l']:.4f}", f"{R['beta_l']:.4f}"),
    ("Cost of equity", "USD: y_US + βL·ERP ; local: (1+Re$)·k − 1",
     f"{pct(y_us, 3)} + {R['beta_l']:.4f} × {pct(erp, 2)} ; (1+{U['re']:.5f})×{k:.5f} − 1",
     pct(U["re"], 3), pct(L["re"], 3)),
    ("Pre-tax cost of debt", "USD: y_US + s ; local: y_F + s_F",
     f"{pct(y_us, 3)} + {pct(s_usd, 3)} ; {pct(y_f, 3)} + {pct(L['spread'], 3)}",
     pct(U["rd_pre"], 3), pct(L["rd_pre"], 3)),
    ("After-tax cost of debt", "Rd × (1 − t)", f"× (1 − {t_proj:.4f})",
     pct(U["rd_after"], 3), pct(L["rd_after"], 3)),
    ("WACC", "(1 − w_d)·Re + w_d·Rd·(1 − t)", f"{1 - wd:.2f}·Re + {wd:.2f}·Rd(1−t)",
     pct(U["wacc"], 3), pct(L["wacc"], 3)),
]
step_df = pd.DataFrame(steps, columns=["Step", "Formula", "Plugged in", "USD", ccy_f])
st.table(step_df.set_index("Step"))
st.caption(f"k = (1 + y_F) / (1 + y_US) = (1 + {y_f:.5f}) / (1 + {y_us:.5f}) = {k:.6f}. "
           f"Local BBB spread is **{'manual' if s_f is not None else 'auto'}**: "
           + (f"auto = (1 + Rd$)·k − 1 − y_F = {pct(L['spread_auto'], 3)}." if s_f is None
              else f"manual {pct(s_f, 3)} (auto would be {pct(L['spread_auto'], 3)})."))

# --------------------------------------------------------------------------
# Built-in verification
# --------------------------------------------------------------------------
with st.expander("✅ Built-in verification checks (run live on your current inputs)", expanded=False):
    tol = 1e-12
    a = engine(bu, t_proj, wd, erp, y_us, y_us, s_usd, None)   # equal yields, override off
    c_eq = all(abs(a["usd"][x] - a["loc"][x]) < tol for x in keys)
    b = engine(bu, t_proj, 0.0, erp, y_us, y_f, s_usd, s_f)    # zero debt
    c_zd = abs(b["usd"]["wacc"] - b["usd"]["re"]) < tol and abs(b["loc"]["wacc"] - b["loc"]["re"]) < tol
    o1 = engine(bu, t_proj, wd, erp, y_us, y_f, s_usd, None)
    o2 = engine(bu, t_proj, wd, erp, y_us, y_f, s_usd, o1["loc"]["spread_auto"] + 0.02)
    c_ov = all(abs(o1["usd"][x] - o2["usd"][x]) < tol for x in keys) and o1["loc"]["wacc"] != o2["loc"]["wacc"]
    checks = [
        (c_eq, "Equal government bond yields → equal results",
         f"With y_F set to y_US = {pct(y_us, 3)} and the spread override off: "
         f"USD WACC {pct(a['usd']['wacc'], 4)} vs local WACC {pct(a['loc']['wacc'], 4)}."),
        (c_zd, "Zero debt → WACC equals cost of equity",
         f"w_d = 0: USD WACC {pct(b['usd']['wacc'], 4)} = Re {pct(b['usd']['re'], 4)}; "
         f"local WACC {pct(b['loc']['wacc'], 4)} = Re {pct(b['loc']['re'], 4)}."),
        (c_ov, "Overriding the local spread leaves USD results unchanged",
         f"Local spread +2 pp: USD WACC stays {pct(o2['usd']['wacc'], 4)}; "
         f"local WACC moves {pct(o1['loc']['wacc'], 4)} → {pct(o2['loc']['wacc'], 4)}."),
    ]
    for ok, title, detail in checks:
        st.markdown(f'<div class="check {"ok" if ok else "bad"}">{"✅" if ok else "❌"} <b>{title}</b><br>'
                    f'<span style="font-size:.88rem;opacity:.85">{detail}</span></div>', unsafe_allow_html=True)

# --------------------------------------------------------------------------
# All-industry comparison
# --------------------------------------------------------------------------
st.markdown("### 🏭 All-industry comparison")
st.caption(f"Every Damodaran industry with the same {name_f} inputs: tax {pct(t_proj)}, debt {wd * 100:.0f}%, "
           f"ERP {erp * 100:.1f}%. The manual beta override applies only to the selected industry.")
bus = np.array([bu if ind == industry else BETAS[ind] for ind in industries], dtype=float)
A = engine(bus, t_proj, wd, erp, y_us, y_f, s_usd, s_f)
all_df = pd.DataFrame({
    "Industry": industries,
    "Unlevered beta": bus,
    "Levered beta": A["beta_l"],
    "Cost of equity USD (%)": A["usd"]["re"] * 100,
    f"Cost of equity {ccy_f} (%)": A["loc"]["re"] * 100,
    "After-tax cost of debt USD (%)": np.full(len(bus), U["rd_after"] * 100),
    f"After-tax cost of debt {ccy_f} (%)": np.full(len(bus), L["rd_after"] * 100),
    "WACC USD (%)": A["usd"]["wacc"] * 100,
    f"WACC {ccy_f} (%)": A["loc"]["wacc"] * 100,
})
all_df["WACC gap (pp)"] = all_df[f"WACC {ccy_f} (%)"] - all_df["WACC USD (%)"]

tab_chart, tab_table = st.tabs(["📊 Chart", "📋 Table"])
with tab_chart:
    sort_by = st.radio("Sort by", ["WACC USD", f"WACC {ccy_f}", "Unlevered beta", "A–Z"],
                       horizontal=True, key="sort_by")
    col = {"WACC USD": "WACC USD (%)", f"WACC {ccy_f}": f"WACC {ccy_f} (%)",
           "Unlevered beta": "Unlevered beta"}.get(sort_by)
    d = all_df.sort_values(col, ascending=True) if col else all_df.sort_values("Industry", ascending=False)
    sel = d["Industry"] == industry
    f2 = go.Figure()
    for i_, (_, r) in enumerate(d.iterrows()):
        f2.add_shape(type="line", x0=r["WACC USD (%)"], x1=r[f"WACC {ccy_f} (%)"], y0=r["Industry"],
                     y1=r["Industry"], line=dict(color="rgba(128,128,128,.45)", width=2))
    f2.add_scatter(x=d["WACC USD (%)"], y=d["Industry"], mode="markers", name="WACC USD",
                   marker=dict(color=C_USD, size=9),
                   hovertemplate="%{y}<br>WACC USD %{x:.2f}%<extra></extra>")
    if iso != "USA":
        f2.add_scatter(x=d[f"WACC {ccy_f} (%)"], y=d["Industry"], mode="markers", name=f"WACC {ccy_f}",
                       marker=dict(color=C_LOC, size=9),
                       hovertemplate="%{y}<br>WACC " + ccy_f + " %{x:.2f}%<extra></extra>")
    hi = d[sel]
    f2.add_scatter(x=hi["WACC USD (%)"], y=hi["Industry"], mode="markers", name="Your industry",
                   marker=dict(color="#F59E0B", size=18, symbol="star", line=dict(color="#000", width=1)),
                   hoverinfo="skip")
    f2.update_layout(height=max(500, 17 * len(d) + 120), margin=dict(l=10, r=10, t=40, b=10),
                     xaxis_title="WACC (%)", legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom"),
                     yaxis=dict(tickfont=dict(size=10)))
    st.plotly_chart(f2, width="stretch", config={"displayModeBar": False})
with tab_table:
    st.dataframe(all_df.round(4), width="stretch", hide_index=True, height=480)

# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------
st.markdown("### ⬇️ Download")
summary = pd.DataFrame([
    ("Industry", industry, industry),
    ("Country / currency", "United States / USD", f"{name_f} / {ccy_f}"),
    ("Unlevered beta", bu, bu),
    ("Project tax rate source", tax_src, tax_src),
    ("Project tax rate (%)", t_proj * 100, t_proj * 100),
    ("Debt share D/(D+E) (%)", wd * 100, wd * 100),
    ("Equity risk premium (%)", erp * 100, erp * 100),
    ("Levered beta", R["beta_l"], R["beta_l"]),
    ("10Y government yield (%)", y_us * 100, y_f * 100),
    ("BBB spread (%)", U["spread"] * 100, L["spread"] * 100),
    ("Local spread mode", "Damodaran", "manual" if s_f is not None else "auto"),
    ("Cost of equity (%)", U["re"] * 100, L["re"] * 100),
    ("Pre-tax cost of debt (%)", U["rd_pre"] * 100, L["rd_pre"] * 100),
    ("After-tax cost of debt (%)", U["rd_after"] * 100, L["rd_after"] * 100),
    ("WACC (%)", U["wacc"] * 100, L["wacc"] * 100),
    ("Data fetched", "; ".join(fetched), "; ".join(fetched)),
], columns=["Item", "USD", ccy_f])
d1, d2 = st.columns(2)
slug_ind = re.sub(r"[^A-Za-z0-9]+", "_", industry).strip("_")
d1.download_button("⬇️ Results (selected industry) — CSV", summary.to_csv(index=False).encode("utf-8"),
                   file_name=f"cost_of_capital_{slug_ind}_{iso}.csv", mime="text/csv", width="stretch")
d2.download_button("⬇️ All-industry comparison — CSV", all_df.to_csv(index=False).encode("utf-8"),
                   file_name=f"cost_of_capital_all_industries_{iso}.csv", mime="text/csv", width="stretch")

# --------------------------------------------------------------------------
# Assumptions
# --------------------------------------------------------------------------
with st.expander("📚 Main assumptions & formulas", expanded=False):
    st.markdown(
        f"""
**1. Beta (bottom-up).** Damodaran's industry *unlevered* beta for U.S. firms is re-levered at your target
capital structure with the Hamada formula:
"""
    )
    st.latex(r"\beta_L=\beta_U\left[1+(1-t)\frac{D}{E}\right],\qquad \frac{D}{E}=\frac{w_d}{1-w_d}")
    st.markdown("**2. USD costs (CAPM + default spread).** The U.S. 10-year Treasury is the USD risk-free rate.")
    st.latex(r"R_E^{\$}=y_{US}+\beta_L\cdot ERP\qquad R_D^{\$}=y_{US}+s_{BBB}")
    st.markdown(
        "**3. Local-currency costs (yield-differential / relative-PPP conversion).** The gap between the two "
        "10-year government yields is treated as the expected inflation (depreciation) differential, so a USD "
        "rate is converted with the Fisher-style factor *k*:"
    )
    st.latex(r"R^{F}=(1+R^{\$})\cdot\frac{1+y_F}{1+y_{US}}-1")
    st.markdown(
        "The local pre-tax cost of debt is converted the same way, which implies a local BBB spread "
        "*s_F = R_D^F − y_F*. If you switch on the manual local spread, the app uses *R_D^F = y_F + s_F* instead. "
        "This changes only the local-currency results."
    )
    st.latex(r"WACC=(1-w_d)\,R_E+w_d\,R_D\,(1-t)")
    st.markdown(
        f"""
**4. Same project parameters in both currencies.** The tax rate (U.S. or {name_f}, your choice), debt share
and ERP are shared, so the two columns differ **only** through the yield gap (and the local spread, if overridden).

**Caveats.**
* Betas come from U.S.-listed firms. The ERP is a single mature-market premium with no separate country-risk premium.
* Government yields include each sovereign's own default risk, so for riskier sovereigns the "risk-free" rate
  includes some country risk.
* The OECD rate is the **combined** (central + sub-central) statutory CIT rate for the latest year available.
  It is not an effective rate.
* Trading Economics quotes are taken from each country's 10-year bond page. The `/bonds` overview table loads
  behind a bot check, so it is not scraped.
"""
    )

st.caption("Data: Aswath Damodaran (NYU Stern), OECD Corporate Tax Statistics, Trading Economics. "
           "Flags: flagcdn.com. Built with Streamlit & Plotly. Code written with Claude (Anthropic) — "
           "model Claude Opus 5.5, November 2026. Verify before relying on results.")
