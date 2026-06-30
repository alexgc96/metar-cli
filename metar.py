#!/usr/bin/env python3
"""metar-cli — METAR + TAF terminal dashboard"""

import argparse
import csv
import html
import math
import os
import re
import sys
import termios
import tty
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns

console = Console()
CONFIG_FILE = Path.home() / ".config" / "metar" / "config"
FALLBACK_ICAO = "MMML"
STALE_THRESHOLD_MINS = 60
_metar_cache: dict = {}


def obs_age_mins(obs_time):
    try:
        dt = datetime.fromtimestamp(int(obs_time), tz=timezone.utc)
        return int((datetime.now(tz=timezone.utc) - dt).total_seconds() / 60)
    except Exception:
        return 0


def get_default_icao():
    if icao := os.environ.get("METAR_ICAO"):
        return icao.upper()
    if CONFIG_FILE.exists():
        val = CONFIG_FILE.read_text().strip()
        if val:
            return val.upper()
    return FALLBACK_ICAO


def set_default_icao(icao):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(icao.upper() + "\n")
    console.print(f"Default station set to [bold]{icao.upper()}[/bold]  ({CONFIG_FILE})")
METAR_URL = "https://aviationweather.gov/api/data/metar"
TAF_URL   = "https://aviationweather.gov/api/data/taf"
SIGMET_URL = "https://aviationweather.gov/api/data/airsigmet"
ASOS_URL  = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

FR_STYLES = {
    "VFR":  ("green",   "bold white on green"),
    "MVFR": ("blue",    "bold white on blue"),
    "IFR":  ("red",     "bold white on red"),
    "LIFR": ("magenta", "bold white on magenta"),
}

ROSE_GRID = [
    ["↖", "↑", "↗"],
    ["←", "·", "→"],
    ["↙", "↓", "↘"],
]
ROSE_POS = {
    "N":  (2, 1), "NE": (2, 0), "E":  (1, 0), "SE": (0, 0),
    "S":  (0, 1), "SW": (0, 2), "W":  (1, 2), "NW": (2, 2),
}

CHANGE_STYLES = {
    "FM":     "bold cyan",
    "BECMG":  "bold yellow",
    "TEMPO":  "bold magenta",
    "PROB30": "dim magenta",
    "PROB40": "dim magenta",
}


def deg_to_cardinal(deg):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(float(deg) / 45) % 8]


def render_rose(wdir, wspd, color):
    active = ROSE_POS[deg_to_cardinal(wdir)] if wdir and wspd > 0 else None
    t = Text()
    for r in range(3):
        for c in range(3):
            ch = ROSE_GRID[r][c]
            style = f"bold {color}" if active and (r, c) == active else "dim"
            t.append(ch, style=style)
            t.append(" ")
        if r < 2:
            t.append("\n")
    return t


SPARKS = "▁▂▃▄▅▆▇█"


def sparkline(values):
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return "─" * len(values)
    lo, hi = min(clean), max(clean)
    if lo == hi:
        return SPARKS[3] * len(values)
    return "".join(
        SPARKS[round((v - lo) / (hi - lo) * 7)] if v is not None else " "
        for v in values
    )


def fetch_metar(icao):
    resp = requests.get(METAR_URL, params={"ids": icao, "format": "json"}, timeout=10)
    resp.raise_for_status()
    if not resp.content:
        raise ValueError(f"No METAR data for {icao}")
    data = resp.json()
    if not data:
        raise ValueError(f"No METAR data for {icao}")
    _metar_cache[icao] = data[0]
    return data[0]


def fetch_taf(icao):
    resp = requests.get(TAF_URL, params={"ids": icao, "format": "json"}, timeout=10)
    resp.raise_for_status()
    if not resp.content:
        return None
    data = resp.json()
    return data[0] if data else None


def fetch_sigmet(lat, lon):
    resp = requests.get(SIGMET_URL, params={"format": "json"}, timeout=10)
    resp.raise_for_status()
    if not resp.content:
        return []
    data = resp.json()
    if not data:
        return []
    # Filter by proximity to station lat/lon (approx 100nm radius)
    filtered = []
    for item in data:
        # Items may have lat/lon or we display all if available
        filtered.append(item)
    return filtered[:10]  # Limit to 10 most recent


def fetch_runways(icao):
    cache_dir = Path.home() / ".cache" / "metar"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "runways.csv"

    if not cache_file.exists():
        try:
            resp = requests.get("https://ourairports.com/data/runways.csv", timeout=10)
            resp.raise_for_status()
            cache_file.write_text(resp.text)
        except requests.RequestException:
            return []

    try:
        content = cache_file.read_text()
        reader = csv.DictReader(content.splitlines())
        runways = []
        for row in reader:
            if row.get("airport_ident", "").upper() == icao:
                runways.append(row)
        return runways
    except Exception:
        return []


def calc_crosswind(wind_dir_deg, wind_speed_kt, runway_heading_deg):
    if not wind_dir_deg or wind_speed_kt is None or wind_speed_kt == 0:
        return None, None

    wind_rad = math.radians(float(wind_dir_deg))
    runway_rad = math.radians(float(runway_heading_deg))

    angle_diff = wind_rad - runway_rad

    headwind = wind_speed_kt * math.cos(angle_diff)
    crosswind = wind_speed_kt * math.sin(angle_diff)

    return headwind, crosswind


def render_crosswind(runway_info, wind_dir, wind_speed, wind_gust):
    runway_id = runway_info.get("runway_ident", "??")
    le_heading = runway_info.get("le_heading_degT")
    he_heading = runway_info.get("he_heading_degT")

    t = Text()
    t.append(f"runway {runway_id}\n\n", style="bold white")

    if wind_dir == "VRB" or wind_speed == 0 or wind_speed is None:
        t.append("calm or variable wind\n", style="dim")
        return Panel(t, title="[dim]crosswind[/dim]", border_style="dim")

    if le_heading:
        t.append(f"heading {int(le_heading)}°", style="dim white")
        hwd, xwd = calc_crosswind(wind_dir, wind_speed, le_heading)
        if hwd is not None:
            t.append(f"  headwind: ", style="dim")
            t.append(f"{hwd:+.1f}kt", style="bold cyan" if hwd > 0 else "bold red")
            t.append(f"  crosswind: ", style="dim")
            t.append(f"{abs(xwd):.1f}kt", style="bold white")
            if wind_gust:
                gust_hwd, gust_xwd = calc_crosswind(wind_dir, wind_gust, le_heading)
                t.append(f" (gust ", style="dim")
                t.append(f"{abs(gust_xwd):.1f}kt", style="bold yellow")
                t.append(")", style="dim")
        t.append("\n")

    if he_heading and le_heading and int(le_heading) != int(he_heading):
        t.append(f"heading {int(he_heading)}°", style="dim white")
        hwd, xwd = calc_crosswind(wind_dir, wind_speed, he_heading)
        if hwd is not None:
            t.append(f"  headwind: ", style="dim")
            t.append(f"{hwd:+.1f}kt", style="bold cyan" if hwd > 0 else "bold red")
            t.append(f"  crosswind: ", style="dim")
            t.append(f"{abs(xwd):.1f}kt", style="bold white")
            if wind_gust:
                gust_hwd, gust_xwd = calc_crosswind(wind_dir, wind_gust, he_heading)
                t.append(f" (gust ", style="dim")
                t.append(f"{abs(gust_xwd):.1f}kt", style="bold yellow")
                t.append(")", style="dim")
        t.append("\n")

    return Panel(t, title="[dim]crosswind[/dim]", border_style="dim")


def fetch_history(icao, hours=6):
    now   = datetime.now(tz=timezone.utc)
    start = now - timedelta(hours=hours)
    resp  = requests.get(ASOS_URL, params={
        "station": icao, "data": "tmpf,drct,sknt,alti",
        "year1": start.year, "month1": start.month, "day1": start.day, "hour1": start.hour,
        "year2": now.year,   "month2": now.month,   "day2": now.day,   "hour2": now.hour,
        "tz": "UTC", "format": "onlycomma", "latlon": "no", "missing": "null",
    }, timeout=10)
    records = []
    for line in resp.text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            tmpf = float(parts[2]) if parts[2] != "null" else None
            wspd = float(parts[4]) if parts[4] != "null" else None
            alti = float(parts[5]) if parts[5] != "null" else None
            records.append({
                "temp": (tmpf - 32) * 5 / 9 if tmpf is not None else None,
                "wspd": wspd,
                "inhg": alti,
            })
        except (ValueError, IndexError):
            continue
    return records


def age_str(obs_time):
    try:
        dt = datetime.fromtimestamp(int(obs_time), tz=timezone.utc)
        mins = int((datetime.now(tz=timezone.utc) - dt).total_seconds() / 60)
        return f"{mins}m ago"
    except Exception:
        return ""


def fmt_time(ts):
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%d/%Hz")
    except Exception:
        return "??Z"


def get_ceiling(clouds):
    for layer in (clouds or []):
        if layer.get("cover") in ("BKN", "OVC"):
            return f"{layer['base']:,} ft"
    return "None"


_WX_INTENSITY  = {"-": "light", "+": "heavy"}
_WX_DESCRIPTOR = {
    "TS": "thunderstorm", "FZ": "freezing", "BL": "blowing",
    "DR": "drifting",     "BC": "patchy",   "MI": "shallow",
    "PR": "partial",      "SH": None,  # handled as suffix "showers"
}
_WX_PHENOM = {
    "DZ": "drizzle",  "RA": "rain",    "SN": "snow",   "SG": "snow grains",
    "IC": "ice",      "PL": "pellets", "GR": "hail",   "GS": "small hail",
    "UP": "precip",   "BR": "mist",    "FG": "fog",    "FU": "smoke",
    "VA": "ash",      "DU": "dust",    "SA": "sand",   "HZ": "haze",
    "PY": "spray",    "PO": "dust whirls", "SQ": "squalls",
    "FC": "funnel cloud", "SS": "sandstorm", "DS": "duststorm",
}

def _decode_wx_token(tok):
    i = 0
    nearby = False
    intensity = ""
    descs = []
    phenom = []

    if tok[i:i+2] == "VC":
        nearby = True
        i += 2

    if i < len(tok) and tok[i] in "-+":
        intensity = _WX_INTENSITY[tok[i]]
        i += 1

    while i < len(tok):
        code = tok[i:i+2]
        if not code:
            break
        if code in _WX_DESCRIPTOR:
            descs.append(code)
            i += 2
        elif code in _WX_PHENOM:
            phenom.append(_WX_PHENOM[code])
            i += 2
        else:
            i += 1

    words = []
    if intensity:
        words.append(intensity)
    for d in ("TS", "FZ", "BL", "DR", "BC", "MI", "PR"):
        if d in descs:
            words.append(_WX_DESCRIPTOR[d])
    words.extend(phenom)
    if "SH" in descs:
        words.append("showers")
    if nearby:
        words.append("nearby")
    return " ".join(words)


def decode_wx(wx_str):
    if not wx_str:
        return ""
    return "  ·  ".join(_decode_wx_token(t) for t in wx_str.split() if t)


def hpa_to_inhg(hpa):
    return f"{float(hpa) * 0.02953:.2f}"


MAX_SPARK_POINTS = 12

def _sample(values, n=MAX_SPARK_POINTS):
    if len(values) <= n:
        return values
    step = len(values) / n
    return [values[round(i * step)] for i in range(n)]


def render_history(history):
    if len(history) < 2:
        return None
    all_temps = [r.get("temp") for r in history]
    all_winds = [r.get("wspd") for r in history]
    all_inhgs = [r.get("inhg") for r in history]

    def cell(label, all_vals, spark_style, fmt, unit):
        clean = [v for v in all_vals if v is not None]
        t = Text()
        t.append(f"{label}  ", style="dim")
        t.append(sparkline(_sample(all_vals)), style=f"bold {spark_style}")
        if clean:
            t.append(f"  {fmt.format(min(clean))}→{fmt.format(max(clean))} {unit}", style=f"dim {spark_style}")
        return t

    tbl = Table(box=None, show_header=False, padding=(0, 3), expand=False)
    tbl.add_column()
    tbl.add_column()
    tbl.add_column()
    tbl.add_row(
        cell("temp", all_temps, "yellow", "{:.0f}", "°C"),
        cell("wind", all_winds, "cyan",   "{:.0f}", "kt"),
        cell("QNH",  all_inhgs, "white",  "{:.2f}", "inHg"),
    )
    return tbl


def parse_iso(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        mins = int((datetime.now(tz=timezone.utc) - dt).total_seconds() / 60)
        return f"{mins}m ago"
    except Exception:
        return ""


def render_taf(taf):
    if not taf:
        return

    valid_from = fmt_time(taf.get("validTimeFrom", 0))
    valid_to   = fmt_time(taf.get("validTimeTo", 0))
    issued     = parse_iso(taf.get("issueTime", ""))

    t = Text()
    t.append(f"valid {valid_from} → {valid_to}", style="dim white")
    t.append(f"   issued {issued}\n\n", style="dim cyan")

    for period in taf.get("fcsts", []):
        change = period.get("fcstChange") or "BASE"
        time_from = fmt_time(period.get("timeFrom", 0))
        time_to   = fmt_time(period.get("timeTo", 0))

        label_style = CHANGE_STYLES.get(change, "bold white")

        t.append(f"{change:<6} ", style=label_style)
        t.append(f"{time_from}→{time_to}  ", style="dim")

        wdir = period.get("wdir")
        wspd = period.get("wspd") or 0
        wgst = period.get("wgst")
        if wspd == 0 or wspd is None:
            t.append("Calm  ", style="cyan")
        else:
            t.append(f"{int(wspd)}", style="bold cyan")
            if wgst:
                t.append(f"G{int(wgst)}", style="bold red")
            t.append("kt", style="cyan")
            if wdir == "VRB":
                t.append(" VRB", style="dim cyan")
            elif wdir is not None:
                card = deg_to_cardinal(wdir)
                t.append(f" {int(wdir)}°{card}", style="dim cyan")
            t.append("  ")

        vis = period.get("visib")
        if vis is not None:
            t.append(f"{vis}SM  ", style="white")

        clouds = period.get("clouds") or []
        for c in clouds:
            cover = c.get("cover", "")
            base  = c.get("base")
            if cover == "SKC" or cover == "CLR":
                t.append("SKC  ", style="dim")
            elif base is not None:
                t.append(f"{cover} {base:,}ft  ", style="dim white")

        wx = period.get("wxString")
        if wx:
            t.append(wx, style="bold yellow")

        t.append("\n")

    raw = taf.get("rawTAF", "")
    if raw:
        t.append("\n")
        t.append(raw, style="dim white")

    console.print(Panel(t, title="[dim]TAF[/dim]", border_style="dim"))


def render_sigmet(sigmets):
    if not sigmets:
        return

    t = Text()
    if not sigmets:
        t.append("no active SIGMETs/AIRMETs", style="dim")
        console.print(Panel(t, title="[dim]SIGMETs / AIRMETs[/dim]", border_style="dim"))
        return

    for item in sigmets:
        hazard = item.get("hazard", "UNKNOWN")
        sigmet_type = item.get("type", "SIGMET")
        valid_from = parse_iso(item.get("validTimeFrom", ""))
        valid_to = parse_iso(item.get("validTimeTo", ""))
        raw_text = item.get("rawSigmet", "")

        # Color code by type
        if sigmet_type == "SIGMET":
            type_style = "bold red"
        elif sigmet_type == "AIRMET":
            type_style = "bold yellow"
        else:
            type_style = "bold white"

        t.append(f"{sigmet_type} ", style=type_style)
        t.append(f"{hazard}  ", style="bold white")
        t.append(f"{valid_from} → {valid_to}", style="dim")
        t.append("\n")

        if raw_text:
            t.append(raw_text, style="dim white")
            t.append("\n\n")

    console.print(Panel(t, title="[dim]SIGMETs / AIRMETs[/dim]", border_style="dim"))


def density_alt(temp_c, altim_hpa, elev_m):
    elev_ft     = elev_m * 3.28084
    altim_inhg  = altim_hpa * 0.02953
    pa          = (29.92 - altim_inhg) * 1000 + elev_ft
    isa_temp    = 15.0 - (1.98 * pa / 1000)
    return round(pa + 120 * (temp_c - isa_temp))


def parse_remarks(raw):
    if "RMK" not in raw:
        return []
    rmk = raw.split("RMK", 1)[1].strip()
    items = []
    tokens = rmk.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]

        m = re.match(r'^SLP(\d{3})$', tok)
        if m:
            v = int(m.group(1))
            hpa = (1000 + v / 10) if v < 500 else (900 + v / 10)
            items.append(("SLP", f"{hpa:.1f} hPa"))

        elif re.match(r'^T[01]\d{3}[01]\d{3}$', tok):
            ts, ds = tok[1:5], tok[5:]
            tv = int(ts[1:]) / 10 * (-1 if ts[0] == "1" else 1)
            dv = int(ds[1:]) / 10 * (-1 if ds[0] == "1" else 1)
            items.append(("T/Td", f"{tv:.1f}° / {dv:.1f}°"))

        elif tok == "AO2":
            items.append(("stn", "ASOS / auto"))
        elif tok == "AO1":
            items.append(("stn", "auto (no precip ID)"))

        elif tok == "PK" and i + 2 < len(tokens) and tokens[i + 1] == "WND":
            m2 = re.match(r'^(\d{3})(\d{2,3})/(\d{4})$', tokens[i + 2])
            if m2:
                items.append(("pk wind", f"{m2.group(2)}kt {m2.group(1)}° :{m2.group(3)[2:]}"))
                i += 2

        elif tok == "WSHFT" and i + 1 < len(tokens):
            t_str = tokens[i + 1]
            items.append(("wshft", f":{t_str[2:]}"))
            i += 1

        elif tok == "PRESRR":
            items.append(("pres Δ", "rising rapidly"))
        elif tok == "PRESFR":
            items.append(("pres Δ", "falling rapidly"))

        elif re.match(r'^P\d{4}$', tok):
            v = int(tok[1:])
            items.append(("precip", "trace" if v == 0 else f"{v / 100:.2f} in"))

        elif re.match(r'^6\d{4}$', tok):
            v = int(tok[1:])
            items.append(("6h precip", "trace" if v == 0 else f"{v / 100:.2f} in"))

        elif tok == "TSNO":
            items.append(("TS sensor", "N/A"))
        elif tok == "RVRNO":
            items.append(("RVR", "N/A"))
        elif tok == "FZRANO":
            items.append(("FZRA sensor", "N/A"))
        elif tok == "PWINO":
            items.append(("precip ID", "N/A"))

        elif tok == "$":
            items.append(("maint", "check needed"))

        i += 1
    return items


def render_analysis_panel(rmk_items):
    t = Text()
    for label, val in rmk_items:
        t.append(f"{label:<10}", style="dim")
        t.append(val + "\n", style="white")
    if not rmk_items:
        t.append("no remarks", style="dim")
    return Panel(t, title="[dim]remarks[/dim]", border_style="dim")


def show_station(icao, show_taf=False, raw_only=False, show_sigmet=False, crosswind_runway=None):
    stale_reason = None
    try:
        m = fetch_metar(icao)
        age = obs_age_mins(m.get("obsTime", 0))
        if age > STALE_THRESHOLD_MINS:
            stale_reason = f"observation is {age}m old"
    except (ValueError, requests.RequestException) as e:
        if icao in _metar_cache:
            m = _metar_cache[icao]
            stale_reason = "live fetch failed — showing last known observation"
        else:
            raise
    history = fetch_history(icao)

    fr     = m.get("fltCat") or m.get("flightCategory", "VFR")
    temp   = m.get("temp")
    dewp   = m.get("dewp")
    wdir   = m.get("wdir")
    wspd   = m.get("wspd", 0)
    wgst   = m.get("wgst")
    visib  = m.get("visib", "—")
    altim  = m.get("altim")
    elev   = m.get("elev")
    clouds = m.get("clouds", [])
    wx     = m.get("wxString") or ""
    raw    = m.get("rawOb", "")
    name   = m.get("name", "")
    obs    = m.get("obsTime", 0)

    if raw_only:
        console.print(raw)
        return

    fr_color, fr_style = FR_STYLES.get(fr, ("white", "bold white"))

    # ── Header ──────────────────────────────────────────────────────────
    hdr = Text()
    hdr.append(f"METAR {icao}", style="bold white")
    if name:
        hdr.append(f"  ·  {name}", style="dim white")
    hdr.append(f"   {age_str(obs)}", style="dim cyan")
    console.print(hdr)
    console.rule(style="dim white")

    if stale_reason:
        console.print(Panel(
            Text(f"⚠  stale data  ·  {stale_reason}", style="bold yellow"),
            border_style="yellow", expand=False,
        ))

    # ── Stat cards ───────────────────────────────────────────────────────
    stats = Table(box=None, show_header=False, padding=(0, 2), expand=False)
    for _ in range(6):
        stats.add_column(justify="center")

    fr_cell = Text(f" {fr} ", style=fr_style)

    temp_cell = Text()
    if temp is not None:
        temp_cell.append(f"{int(temp)}°C", style="bold yellow")
        if dewp is not None:
            temp_cell.append(f" / {int(dewp)}°", style="dim yellow")

    wind_val = Text()
    wind_sub = Text("")
    if not wspd or wspd == 0:
        wind_val.append("Calm", style="bold cyan")
    else:
        wind_val.append(f"{int(wspd)}", style="bold cyan")
        if wgst:
            wind_val.append(f"G{int(wgst)}", style="bold red")
        wind_val.append("kt", style="cyan")
        if wdir == "VRB":
            wind_val.append("  VRB", style="dim cyan")
            wind_sub = Text("variable", style="dim")
        else:
            wind_val.append(f"  {int(wdir)}°", style="dim cyan")
            wind_sub = Text(deg_to_cardinal(wdir), style="dim")

    vis_cell  = Text(f"{visib} mi", style="bold white")
    ceil_cell = Text(get_ceiling(clouds), style="bold white")
    qnh_cell  = Text(f"{hpa_to_inhg(altim)} inHg" if altim else "—", style="bold white")

    stats.add_row(fr_cell, temp_cell, wind_val, vis_cell, ceil_cell, qnh_cell)
    stats.add_row(
        Text(""),
        Text(decode_wx(wx) or "clear", style="dim"),
        wind_sub if wspd else Text(""),
        Text("Visibility", style="dim"),
        Text("Ceiling", style="dim"),
        Text("QNH", style="dim"),
    )

    console.print(stats)
    console.rule(style="dim white")

    # ── Wind rose + cloud layers side by side ────────────────────────────
    rose_text = render_rose(wdir, wspd, fr_color)
    if temp is not None and altim and elev is not None:
        da = density_alt(temp, altim, elev)
        da_style = "bold green" if da < 3000 else ("bold yellow" if da < 5000 else "bold red")
        elev_ft = round(elev * 3.28084)
        rose_text.append("\n──────\n", style="dim")
        rose_text.append("elev  ", style="dim")
        rose_text.append(f"{elev_ft:,}ft\n", style="white")
        rose_text.append("DA    ", style="dim")
        rose_text.append(f"{da:,}ft", style=da_style)
    rose_panel = Panel(rose_text, title="[dim]wind[/dim]", width=18, border_style="dim")

    clouds_text = Text()
    altitudes  = [20000, 12000, 6000, 3000, 1500, 500, 0]
    alt_labels = {20000: "20k", 12000: "12k", 6000: " 6k",
                  3000:  " 3k", 1500:  "1.5", 500:  "500", 0: "sfc"}
    cloud_rows: dict = {}
    for c in (clouds or []):
        base = c.get("base")
        if base is None:
            continue
        nearest = min(altitudes, key=lambda a: abs(a - base))
        cloud_rows.setdefault(nearest, []).append(c["cover"])
    for alt in altitudes:
        clouds_text.append(f"{alt_labels[alt]} │ ", style="dim")
        for cover in cloud_rows.get(alt, []):
            clouds_text.append(f"☁ {cover}", style="bold white")
        clouds_text.append("\n")
    clouds_text.append("    └" + "─" * 12, style="dim")

    clouds_panel = Panel(clouds_text, title="[dim]clouds[/dim]", width=22, border_style="dim")

    rmk_items      = parse_remarks(raw)
    analysis_panel = render_analysis_panel(rmk_items)
    console.print(Columns([rose_panel, clouds_panel, analysis_panel]))
    console.rule(style="dim white")

    # ── Sparkline history ────────────────────────────────────────────────
    hist_text = render_history(history)
    if hist_text:
        console.print(Panel(hist_text, title="[dim]history (6h)[/dim]", border_style="dim"))
        console.rule(style="dim white")

    # ── Raw METAR ────────────────────────────────────────────────────────
    console.print(Panel(Text(raw, style="dim white"), title="[dim]raw[/dim]", border_style="dim"))

    # ── TAF ──────────────────────────────────────────────────────────────
    if show_taf:
        console.rule(style="dim white")
        taf = fetch_taf(icao)
        render_taf(taf)

    # ── SIGMET / AIRMET ──────────────────────────────────────────────────
    if show_sigmet:
        console.rule(style="dim white")
        lat = m.get("lat")
        lon = m.get("lon")
        if lat is not None and lon is not None:
            try:
                sigmets = fetch_sigmet(lat, lon)
                render_sigmet(sigmets)
            except requests.RequestException:
                console.print(Panel(
                    Text("failed to fetch SIGMETs", style="dim yellow"),
                    border_style="yellow",
                ))

    # ── Crosswind ────────────────────────────────────────────────────
    if crosswind_runway:
        console.rule(style="dim white")
        runways = fetch_runways(icao)
        matched = None
        for rwy in runways:
            rwy_id = rwy.get("runway_ident", "")
            if rwy_id.rstrip("LRC").upper() == crosswind_runway.upper():
                matched = rwy
                break
        if matched and wdir and wspd:
            console.print(render_crosswind(matched, wdir, wspd, wgst))
        elif not matched:
            console.print(Panel(
                Text(f"runway {crosswind_runway} not found", style="dim yellow"),
                border_style="yellow",
            ))
        elif not wdir or not wspd:
            console.print(Panel(
                Text("no wind data available", style="dim yellow"),
                border_style="yellow",
            ))


def getch():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _icao_dialog(title, subtitle, label, hint, border_color="#00aaff", error=None):
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.widgets import Frame
    from prompt_toolkit.styles import Style

    result = [None]
    buf = Buffer()

    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        val = buf.text.strip().upper()
        if val:
            result[0] = val
        event.app.exit()

    @kb.add("c-c")
    @kb.add("c-d")
    def _(event):
        event.app.exit()

    def row(content, style=""):
        return Window(
            FormattedTextControl(content),
            height=1,
            align=WindowAlign.CENTER,
            style=style,
        )

    body = [
        Window(height=1),
        row(HTML(f"<b>{title}</b>")),
        row(subtitle, style="fg:#888888"),
        Window(height=1),
    ]

    if error:
        body.append(row(HTML(f"<ansired>✗  {html.escape(error)}</ansired>")))
        body.append(Window(height=1))

    body += [
        row(label, style="fg:#aaaaaa"),
        Window(height=1),
        Frame(
            Window(content=BufferControl(buffer=buf), height=1),
            style="class:input-frame",
        ),
        Window(height=1),
        row(hint, style="fg:#555555"),
        Window(height=1),
    ]

    dialog = Frame(HSplit(body), style="class:outer-frame", width=36)
    root   = HSplit([Window(), VSplit([Window(), dialog, Window()]), Window()])

    style = Style.from_dict({
        "outer-frame frame.border": f"fg:{border_color}",
        "outer-frame frame.label":  f"bold fg:{border_color}",
        "input-frame frame.border": "fg:#334455",
    })

    app = Application(
        layout=Layout(root, focused_element=buf),
        key_bindings=kb,
        style=style,
        full_screen=True,
        mouse_support=False,
    )
    app.run()
    return result[0]


def search_prompt(error=None):
    return _icao_dialog(
        title="✈  metar-cli",
        subtitle="METAR + TAF  ·  terminal dashboard",
        label="input station",
        hint="enter ↵ to search   ctrl+c to quit",
        error=error,
    )


def config_prompt():
    current = get_default_icao()
    return _icao_dialog(
        title="⚙  set default station",
        subtitle=f"current default: {current}",
        label="new default ICAO",
        hint="enter ↵ to save   ctrl+c to cancel",
        border_color="#ffaa00",
    )


def runway_picker_prompt(icao):
    runways = fetch_runways(icao)
    if not runways:
        return None

    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window, VSplit, HSplit
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    result = [None]
    selected = [0]

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        selected[0] = max(0, selected[0] - 1)

    @kb.add("down")
    def _(event):
        selected[0] = min(len(runways) - 1, selected[0] + 1)

    @kb.add("enter")
    def _(event):
        result[0] = runways[selected[0]]
        event.app.exit()

    @kb.add("c-c")
    @kb.add("c-d")
    def _(event):
        event.app.exit()

    def get_text():
        text = "select runway (↑/↓ to navigate, enter to select, ctrl+c to cancel)\n\n"
        for i, rwy in enumerate(runways):
            marker = "► " if i == selected[0] else "  "
            rwy_id = rwy.get("runway_ident", "??")
            text += f"{marker}{rwy_id}\n"
        return text

    root = Window(FormattedTextControl(get_text))
    app = Application(
        layout=Layout(root),
        key_bindings=kb,
        full_screen=True,
        mouse_support=False,
    )
    app.run()
    return result[0]


def interactive_mode():
    icao = None
    show_taf = False
    raw_mode = False
    show_sigmet = False
    crosswind_runway = None
    error = None

    while True:
        # ── Search screen ────────────────────────────────────────────────
        if icao is None:
            icao = search_prompt(error=error)
            error = None
            if icao is None:
                console.clear()
                return

        # ── Display screen ───────────────────────────────────────────────
        console.clear()
        try:
            show_station(icao, show_taf=show_taf, raw_only=raw_mode, show_sigmet=show_sigmet, crosswind_runway=crosswind_runway)
        except (ValueError, requests.RequestException) as e:
            error = str(e)
            icao = None
            continue

        # ── Key bar ──────────────────────────────────────────────────────
        console.print()
        console.rule(style="dim")

        bar = Text(justify="center")
        bar.append("q", style="bold cyan");    bar.append(" quit", style="dim")
        bar.append("   t", style="bold cyan" if not show_taf  else "bold green")
        bar.append(" taf"  + (" ✓" if show_taf  else ""), style="dim" if not show_taf  else "green")
        bar.append("   w", style="bold cyan" if not show_sigmet else "bold green")
        bar.append(" sigmet" + (" ✓" if show_sigmet else ""), style="dim" if not show_sigmet else "green")
        bar.append("   r", style="bold cyan" if not raw_mode else "bold green")
        bar.append(" raw"  + (" ✓" if raw_mode else ""), style="dim" if not raw_mode else "green")
        bar.append("   x", style="bold cyan" if not crosswind_runway else "bold green")
        bar.append(" xwind" + (f" {crosswind_runway}✓" if crosswind_runway else ""), style="dim" if not crosswind_runway else "green")
        bar.append("   s", style="bold cyan"); bar.append(" search", style="dim")
        bar.append("   u", style="bold cyan"); bar.append(" refresh", style="dim")
        bar.append("   c", style="bold cyan"); bar.append(" config", style="dim")
        console.print(bar)

        key = getch()
        if key in ("q", "Q", "\x03"):   # q or Ctrl+C
            console.clear()
            return
        elif key in ("t", "T"):
            show_taf = not show_taf
        elif key in ("w", "W"):
            show_sigmet = not show_sigmet
        elif key in ("r", "R"):
            raw_mode = not raw_mode
        elif key in ("x", "X"):
            runway = runway_picker_prompt(icao)
            if runway:
                crosswind_runway = runway.get("runway_ident")
            else:
                crosswind_runway = None
        elif key in ("s", "S"):
            icao = None
            show_taf = False
            show_sigmet = False
            raw_mode = False
            crosswind_runway = None
        elif key in ("c", "C"):
            new_default = config_prompt()
            if new_default:
                set_default_icao(new_default)


def main():
    parser = argparse.ArgumentParser(
        prog="metar",
        description="Aviation weather dashboard — METAR + TAF",
    )
    parser.add_argument(
        "icao", nargs="*", default=[],
        metavar="ICAO", help="One or more ICAO station codes",
    )
    parser.add_argument("--taf", action="store_true", help="Include TAF forecast block")
    parser.add_argument("--sigmet", action="store_true", help="Include SIGMETs and AIRMETs")
    parser.add_argument("--raw", action="store_true", help="Print raw METAR string only")
    parser.add_argument("--xwind", metavar="RWY", help="Calculate crosswind for runway (e.g., 28, 10L)")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--set-default", metavar="ICAO", help="Save a default station to ~/.config/metar/config")
    args = parser.parse_args()

    if args.set_default:
        set_default_icao(args.set_default)
        return

    if args.interactive:
        interactive_mode()
        return

    stations = [s.upper() for s in args.icao] or [get_default_icao()]
    for i, icao in enumerate(stations):
        if i > 0:
            console.print()
        try:
            show_station(icao, show_taf=args.taf, raw_only=args.raw, show_sigmet=args.sigmet, crosswind_runway=args.xwind)
        except ValueError as e:
            console.print(f"[bold red]error:[/bold red] {e}")
            sys.exit(1)
        except requests.RequestException as e:
            console.print(f"[bold red]network error:[/bold red] {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
# HOWDY! thanks for reading the code ;)  - Alex gc / soup - weekend project finished 13 jun 2026 