# metar-cli

Terminal METAR + TAF dashboard for pilots and aviation nerds. Live weather data rendered straight in your terminal — think wttr.in but aviation-focused.

Default station: **MMML** (General Rodolfo Sánchez Taboada Intl, Mexicali, BC, MX)

```
METAR MMML  ·  Mexicali Intl, BC, MX   12m ago
────────────────────────────────────────────────
  VFR    30°C / 14°   3kt 60°   10+ mi  None  29.71 inHg
          clear          NE    Visibility Ceiling  QNH
────────────────────────────────────────────────
╭─── wind ───╮ ╭──── clouds ────╮ ╭──── remarks ────╮
│ ↖ ↑ ↗      │ │ 20k │          │ │ stn   ASOS/auto │
│ ← · →      │ │ 12k │          │ │ SLP   1008.1 hPa│
│ ↙ ↓ ↘      │ │  6k │          │ │ T/Td  30.0/14.4 │
│ ──────     │ │  3k │          │ ╰─────────────────╯
│ elev  69ft │ │ 1.5 │          │
│ DA  2,141ft│ │ 500 │          │
╰────────────╯ │ sfc │          │
               │     └────────  │
               ╰────────────────╯
────────────────────────────────────────────────
  temp  ▁▂▄▆█▅▃▂▁▂▃▄   30→37 °C
  wind  ▃▂▁▁▂▃▄▃▂▁▂▃    0→10 kt
  QNH   ▅▄▃▄▅▆▇▆▅▄▅▆   29.66→29.72 inHg
────────────────────────────────────────────────
  METAR MMML 130647Z 06003KT 10SM SKC 30/14 A2971
```

-----

## Install

The recommended way is [pipx](https://pipx.pypa.io), which installs `metar` as a global command without polluting your system Python:

```bash
pipx install git+https://github.com/alexgc96/metar-cli.git
```

That’s it. `metar` is now available from anywhere.

**Don’t have pipx?**

```bash
# macOS (MacPorts)
sudo port install pipx

# macOS (Homebrew)
brew install pipx

# Linux / other
pip install --user pipx
```

**For development / contributing:**

```bash
git clone https://github.com/alexgc96/metar-cli.git
cd metar-cli
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

-----

## Usage

```
metar [-h] [--taf] [--raw] [-i] [--set-default ICAO] [ICAO ...]

positional arguments:
  ICAO                One or more ICAO station codes

options:
  -h, --help          show this help message and exit
  --taf               Include TAF forecast block
  --raw               Print raw METAR string only
  -i, --interactive   Interactive mode
  --set-default ICAO  Save a default station to ~/.config/metar/config
```

-----

## Interactive mode (`-i`)

```bash
metar -i
```

Full-screen ICAO search box. Once a station is loaded:

|Key|Action                 |
|---|-----------------------|
|`t`|Toggle TAF forecast    |
|`r`|Toggle raw METAR string|
|`u`|Refresh / re-fetch data|
|`s`|New station search     |
|`c`|Set default station    |
|`q`|Quit                   |

-----

## Data sources

### METAR + TAF — aviationweather.gov

All primary weather data comes from the **Aviation Weather Center (AWC)** public API operated by NOAA/NWS. No API key required.

|Data           |Endpoint                                                         |
|---------------|-----------------------------------------------------------------|
|METAR (current)|`https://aviationweather.gov/api/data/metar?ids=MMML&format=json`|
|TAF (forecast) |`https://aviationweather.gov/api/data/taf?ids=MMML&format=json`  |

**Fields used from METAR JSON:**

- `temp`, `dewp` — temperature and dew point (°C)
- `wdir`, `wspd`, `wgst` — wind direction (°), speed and gust (kt)
- `visib` — visibility (statute miles)
- `altim` — altimeter setting (hPa, converted to inHg for display)
- `clouds` — array of `{cover, base}` objects (e.g. `BKN`, `OVC` at feet MSL)
- `fltCat` — computed flight category (VFR / MVFR / IFR / LIFR)
- `wxString` — present weather string (e.g. `TSRA`, `-RA`, `BR`)
- `rawOb` — full raw METAR string including remarks
- `elev` — station elevation (metres)
- `lat`, `lon` — station coordinates
- `obsTime` — observation Unix timestamp

**Fields used from TAF JSON:**

- `validTimeFrom`, `validTimeTo` — forecast valid period (Unix timestamps)
- `issueTime` — issue time (ISO 8601 string)
- `rawTAF` — full raw TAF string
- `fcsts` — array of forecast periods, each with `timeFrom`, `timeTo`, `fcstChange`, `wdir`, `wspd`, `wgst`, `visib`, `clouds`, `wxString`

### Historical observations — Iowa State Mesonet (ASOS)

The 6-hour sparkline history uses the **Iowa State University Environmental Mesonet** ASOS archive. Free, no auth required.

```
https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
  ?station=MMML
  &data=tmpf,drct,sknt,alti
  &format=onlycomma
  &missing=null
  &tz=UTC
```

**Fields used:** `tmpf` (temp °F, converted to °C), `sknt` (wind speed kt), `alti` (altimeter inHg). Up to 76 observations per 6h window are sampled down to 12 points for the sparkline; the full dataset is used for accurate min/max ranges.

### Computed values

- **Density altitude** — calculated from OAT, altimeter setting, and station elevation using the standard ISA lapse rate formula. No external data required.
- **wx string decode** — parsed locally from the `wxString` field using ICAO intensity/descriptor/phenomenon codes. No external data required.
- **Remarks decode** — parsed locally from the `rawOb` RMK section (SLP, precise T/Td, station type, peak wind, pressure tendency, precip, maintenance flag).

-----

## Configuration

Set a persistent default station:

```bash
metar --set-default KJFK
# saves to ~/.config/metar/config
```

Or use an environment variable (takes priority over the config file):

```bash
export METAR_ICAO=MMML
```

-----

## Safety disclaimer

> **metar-cli is a convenience tool for curiosity and preflight awareness — not a substitute for an official weather briefing.**
> 
> Real and virtual pilots alike should always consult their country’s aviation authority and any flight planning services available to them before flight. In the US this means a standard weather briefing via 1800wxbrief.com or ForeFlight. In Mexico, consult SENEAM and your applicable NOTAMs. In other countries, use whatever official sources your CAA provides.
> 
> A single METAR is a snapshot in time at one point on the ground. It does not capture en-route conditions, winds aloft, SIGMETs, AIRMETs, TFRs, or anything happening above the field. Always get the full picture.

-----

## Stack

- **Python 3.10+**
- [`rich`](https://github.com/Textualize/rich) — terminal layout, panels, color, sparklines
- [`requests`](https://requests.readthedocs.io/) — HTTP
- [`prompt_toolkit`](https://python-prompt-toolkit.readthedocs.io/) — interactive mode UI

-----

## Inspiration

- [wttr.in](https://wttr.in) — terminal weather density as a design goal
- [metar-taf.com](https://metar-taf.com) — MMML dashboard, June 2026