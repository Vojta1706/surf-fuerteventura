#!/usr/bin/env python3
"""Stáhne novou předpověď ze surf-forecast.com a uloží ji do data/forecast.json.

Spouští ho GitHub Action (.github/workflows/update.yml) každých 15 minut. Když surf-forecast nemá
novější předpověď, než jaká už je v datech, skončí bez změny. Jinak stáhne tři body a přílivy,
zkontroluje data, doplní dnešní dřívější časy z minulých dat, nechá scripts/note.js napsat komentář
a soubor přepíše.

  python3 scripts/update.py            normální běh
  python3 scripts/update.py --force    stáhne a uloží data, i když předpověď není nová
  python3 scripts/update.py --debug    jen vypíše, co ze stránek přečetl (nic neuloží)
"""
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "forecast.json"
TZ = ZoneInfo("Atlantic/Canary")
BASE = "https://www.surf-forecast.com/breaks/"
POINTS = {  # bod -> (stránka na surf-forecast, přílivová stanice)
    "majanicho": ("Majanicho", "corralejo"),
    "bajo": ("Rocky-Point_Bajodel-Medio", "corralejo"),
    "esquinzo": ("Playade-Esquinzo_1", "cotillo"),
}
TIDE_PAGES = {"corralejo": "Majanicho", "cotillo": "Playade-Esquinzo_1"}
DIRS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
WS = {"glassy", "off", "cross-off", "cross", "cross-on", "on"}
CZ_DAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
ARGS = set(sys.argv[1:])
DEBUG = "--debug" in ARGS

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
})


def fail(msg):
    print("CHYBA:", msg)
    sys.exit(1)


def get(url):
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}v={int(time.time())}"  # obejít případnou mezipaměť
    for attempt in range(3):
        try:
            r = session.get(url, timeout=40)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            print(f"  {url}: HTTP {r.status_code}")
        except requests.RequestException as e:
            print(f"  {url}: {e}")
        time.sleep(5 * (attempt + 1))
    fail(f"nepodařilo se stáhnout {url}")


def text(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el is not None else ""


def attrs_text(el):
    """Text a všechny hodnoty atributů prvku a jeho potomků (kvůli datům schovaným v atributech)."""
    parts = [text(el)]
    for x in [el] + el.find_all(True):
        for v in x.attrs.values():
            parts.append(" ".join(v) if isinstance(v, list) else str(v))
    return " ".join(parts)


def num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def compass(s):
    """První 16bodový směr v textu (jen samostatná slova velkými písmeny)."""
    for tok in re.findall(r"(?<![A-Za-z])(NNE|ENE|ESE|SSE|SSW|WSW|WNW|NNW|NE|SE|SW|NW|N|E|S|W)(?![A-Za-z])", s or ""):
        return tok
    return None


def deg_to_compass(deg):
    return DIRS[int((deg % 360) / 22.5 + 0.5) % 16]


def table_rows(soup):
    """Řádky předpovědní tabulky podle data-row-name; buňky rozbalené podle colspan."""
    rows = {}
    for tr in soup.select("tr[data-row-name]"):
        name = tr.get("data-row-name")
        if name in rows:
            continue
        cells = []
        for td in tr.find_all("td", recursive=False):
            span = int(td.get("colspan") or 1)
            cells.extend([td] * span)
        rows[name] = cells
    return rows


def debug_dump(label, soup):
    print(f"===== {label}")
    rows = table_rows(soup)
    print("řádky:", list(rows))
    for name, cells in rows.items():
        shown = []
        for td in cells[:6]:
            a = {k: (" ".join(v) if isinstance(v, list) else v) for k, v in td.attrs.items()}
            inner = [{k: (" ".join(v) if isinstance(v, list) else v) for k, v in x.attrs.items() if k.startswith("data-") or k in ("alt", "title", "aria-label")} for x in td.find_all(True)]
            inner = [x for x in inner if x][:3]
            shown.append(f"[{text(td)[:40]!r} {a} {inner}]")
        print(f"- {name} ({len(cells)}): " + " ".join(shown)[:900])
    m = re.search(r"Issued[^\n]{0,80}", soup.get_text(" "))
    print("issued:", m.group() if m else None)


def parse_time(s):
    s = (s or "").strip().lower().replace(" ", "").replace(".", "")
    if s in ("noon", "midday"):
        return "12:00"
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def resolve_day(dom, today):
    """Den v měsíci -> datum nejblíž dnešku (předpověď jde nejvýš ~10 dní dopředu)."""
    for delta in range(-2, 12):
        d = today + dt.timedelta(days=delta)
        if d.day == dom:
            return d
    return None


def parse_issued(soup):
    m = re.search(r"Issued:?\s*(\d{1,2})\s*(am|pm)\s+(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", soup.get_text(" "), re.I)
    if not m:
        return None, None
    h = int(m.group(1)) % 12 + (12 if m.group(2).lower() == "pm" else 0)
    d = dt.date(int(m.group(5)), MONTHS[m.group(4).lower()], int(m.group(3)))
    raw = f"{m.group(1)} {m.group(2).lower()} {int(m.group(3))} {m.group(4).title()} {m.group(5)}"
    return raw, f"{CZ_DAYS[d.weekday()]} {d.day}. {d.month}. {h:02d}:00"


def parse_sea_temp(soup):
    t = soup.get_text(" ")
    for pat in (r"[Ss]ea\s+[Tt]emp\w*\D{0,60}?(\d{1,2}(?:\.\d)?)\s*°", r"[Ww]ater\s+[Tt]emp\w*\D{0,60}?(\d{1,2}(?:\.\d)?)\s*°"):
        m = re.search(pat, t)
        if m and 10 <= float(m.group(1)) <= 32:
            return float(m.group(1))
    return None


def cell_rating(td):
    for x in [td] + td.find_all(True):
        for k in ("data-value", "data-rating", "alt", "title"):
            v = x.get(k)
            if isinstance(v, str) and re.fullmatch(r"\s*\d{1,2}\s*", v):
                return int(v)
    v = num(text(td))
    return int(v) if v is not None and 0 <= v <= 10 else 0


def swell_from_attr(td):
    """surf-forecast ukládá swell do JSON atributu (data-swell-state)."""
    for x in [td] + td.find_all(True):
        raw = x.get("data-swell-state")
        if raw:
            try:
                arr = json.loads(raw)
                arr = [s for s in (arr if isinstance(arr, list) else [arr]) if isinstance(s, dict)]
                if arr:
                    return arr[0]
            except ValueError:
                pass
    return None


def cell_wave(td):
    s = swell_from_attr(td) or {}
    h = num(text(td))
    if h is None and s.get("height") is not None:
        h = float(s["height"])
    d = s.get("letters") or compass(attrs_text(td))
    if not d and s.get("angle") is not None:
        d = deg_to_compass(float(s["angle"]) + 180)  # úhel ikony míří po směru vlny
    p = float(s["period"]) if s.get("period") is not None else None
    return h, d, p


def cell_wind(td):
    w = None
    for x in [td] + td.find_all(True):
        for k in ("data-speed", "data-wind-speed"):
            if x.get(k) and num(x.get(k)) is not None:
                w = num(x.get(k))
                break
        if w is not None:
            break
    if w is None:
        w = num(text(td))
    return w, compass(attrs_text(td))


def parse_forecast(soup, today, days):
    rows = table_rows(soup)
    need = ["days", "time", "wave-height", "periods", "wind"]
    miss = [r for r in need if r not in rows]
    if miss:
        debug_dump("chybí řádky " + ", ".join(miss), soup)
        fail("v tabulce chybí řádky " + ", ".join(miss))
    n = len(rows["time"])
    dates = []
    for td in rows["days"][:n]:
        dom = None
        if td.get("data-date"):
            try:
                dates.append(dt.date.fromisoformat(td["data-date"][:10]))
                continue
            except ValueError:
                pass
        m = re.search(r"\b(\d{1,2})\b", text(td))
        dom = int(m.group(1)) if m else None
        dates.append(resolve_day(dom, today) if dom else None)
    slots = []
    for i in range(n):
        d = dates[i] if i < len(dates) else None
        t = parse_time(text(rows["time"][i]))
        if not d or not t or d not in days or not ("06:00" <= t <= "20:00"):
            continue
        h, sd, p_attr = cell_wave(rows["wave-height"][i])
        p = num(text(rows["periods"][i])) or p_attr
        w, wd = cell_wind(rows["wind"][i])
        slot = {"d": d.isoformat(), "t": t, "h": h, "sd": sd, "p": p,
                "kj": num(text(rows["energy"][i])) if "energy" in rows and i < len(rows["energy"]) else None,
                "w": w, "wd": wd,
                "sf": cell_rating(rows["rating"][i]) if "rating" in rows and i < len(rows["rating"]) else 0}
        for k in ("p", "w", "kj"):
            if isinstance(slot[k], float) and slot[k].is_integer():
                slot[k] = int(slot[k])
        if "wind-state" in rows and i < len(rows["wind-state"]):
            ws = text(rows["wind-state"][i]).lower().replace(" ", "")
            ws = {"crossoff": "cross-off", "crosson": "cross-on"}.get(ws, ws)
            if ws in WS:
                slot["ws"] = ws
        slots.append(slot)
    return slots


TIDE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)?\s*\(?\s*(-?\d+(?:\.\d+)?)\s*m", re.I)


def parse_tides(soup, today, last_day):
    """Přílivy a odlivy z přílivové stránky: řádky tabulky s 'High'/'Low', časem a výškou."""
    out = []
    cur_date = None
    for el in soup.find_all(["tr", "h2", "h3", "h4", "caption", "th"]):
        t = text(el)
        m = re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})", t)
        if m and el.name != "tr":
            cur_date = resolve_day(int(m.group(2)), today)
            continue
        if el.name != "tr":
            continue
        if m:
            cur_date = resolve_day(int(m.group(2)), today)
        kind = "H" if re.search(r"\bhigh\b", t, re.I) else "L" if re.search(r"\blow\b", t, re.I) else None
        tm = TIDE_RE.search(t)
        if not kind or not tm or not cur_date:
            continue
        h, mi = int(tm.group(1)), int(tm.group(2))
        ap = (tm.group(3) or "").lower()
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        out.append({"d": cur_date.isoformat(), "t": f"{h:02d}:{mi:02d}", "k": kind, "m": float(tm.group(4))})
    seen, res = set(), []
    for e in sorted(out, key=lambda e: (e["d"], e["t"])):
        if (e["d"], e["t"]) not in seen and today.isoformat() <= e["d"] <= last_day.isoformat():
            seen.add((e["d"], e["t"]))
            res.append(e)
    return res


def validate(d):
    for pid, (_, st) in POINTS.items():
        S = d["points"][pid]["slots"]
        if len({s["d"] for s in S}) < 2:
            fail(f"{pid}: málo dní ({len(S)} slotů)")
        for s in S:
            if not all(isinstance(s.get(f), (int, float)) for f in ("h", "p", "w")) or s.get("sd") not in DIRS or s.get("wd") not in DIRS:
                fail(f"{pid}: neúplný slot {s}")
            if not (0 < s["h"] < 12 and 3 <= s["p"] <= 25 and 0 <= s["w"] < 150):
                fail(f"{pid}: podezřelé hodnoty {s}")
    for st, T in d["tides"].items():
        if len(T) < 6:
            fail(f"přílivy {st}: málo údajů ({len(T)})")


def main():
    now = dt.datetime.now(TZ)
    today = now.date()
    days = {today + dt.timedelta(days=i) for i in range(3)}
    old = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}

    pages = {pid: get(BASE + slug + "/forecasts/latest?units=m") for pid, (slug, _) in [("esquinzo", POINTS["esquinzo"])]}
    raw, issued = parse_issued(pages["esquinzo"])
    print("surf-forecast:", raw, "| v datech:", old.get("issuedRaw"))
    if DEBUG:
        debug_dump("esquinzo", pages["esquinzo"])
    if not raw:
        if not DEBUG:
            debug_dump("esquinzo", pages["esquinzo"])
        fail("nenašel jsem čas vydání (Issued)")
    if raw == old.get("issuedRaw") and "--force" not in ARGS and not DEBUG:
        print("Nová předpověď zatím není, nic neměním.")
        return

    for pid, (slug, _) in POINTS.items():
        if pid not in pages:
            pages[pid] = get(BASE + slug + "/forecasts/latest?units=m")
    data = {
        "schema": 3,
        "updatedAt": now.replace(microsecond=0).isoformat(),
        "issued": issued,
        "issuedRaw": raw,
        "source": old.get("source") or "surf-forecast.com",
        "sourceUrl": old.get("sourceUrl") or "https://www.surf-forecast.com/",
        "waterTemp": parse_sea_temp(pages["esquinzo"]) or old.get("waterTemp"),
        "note": "", "noteEn": "",
        "points": {}, "tides": {},
        "tideNames": {"corralejo": "Corralejo", "cotillo": "Cotillo"},
    }
    for pid, (slug, st) in POINTS.items():
        r2, _ = parse_issued(pages[pid])
        if r2 != raw:
            print(f"POZOR: {pid} má jiné vydání ({r2}) než Esquinzo ({raw})")
        prev = (old.get("points") or {}).get(pid) or {}
        data["points"][pid] = {"name": prev.get("name") or slug, "url": BASE + slug + "/forecasts/latest",
                               "tides": st, "slots": parse_forecast(pages[pid], today, days)}
        if DEBUG:
            debug_dump(pid, pages[pid])
            print(json.dumps(data["points"][pid]["slots"][:6], ensure_ascii=False))

    last_day = today + dt.timedelta(days=3)
    for st, slug in TIDE_PAGES.items():
        soup = get(BASE + slug + "/tides/latest")
        data["tides"][st] = parse_tides(soup, today, last_day)
        if DEBUG or len(data["tides"][st]) < 6:
            print(f"===== přílivy {st}: {len(data['tides'][st])}", json.dumps(data["tides"][st][:4]))
            if len(data["tides"][st]) < 6:
                for tr in soup.find_all("tr")[:25]:
                    print("  tr:", text(tr)[:160])
    # Když jedné stanici chybí extrém, vezmi ho z druhé (liší se o minuty a cm).
    a, b = data["tides"]["corralejo"], data["tides"]["cotillo"]
    for x, y in ((a, b), (b, a)):
        have = {(e["d"], e["k"], e["t"][:2]) for e in x}
        for e in y:
            if not any(h[0] == e["d"] and h[1] == e["k"] and abs(int(h[2]) - int(e["t"][:2])) <= 1 for h in have):
                x.append(dict(e, est=True))
        x.sort(key=lambda e: (e["d"], e["t"]))
    if DEBUG:
        print("debug: nic neukládám")
        return

    # Dnešní dřívější časy, které už surf-forecast nezobrazuje, zůstanou z minulých dat.
    for pid, p in data["points"].items():
        S = p["slots"]
        if not S:
            continue
        day1 = min(s["d"] for s in S)
        first = min(s["t"] for s in S if s["d"] == day1)
        have = {(s["d"], s["t"]) for s in S}
        add = [s for s in ((old.get("points") or {}).get(pid) or {}).get("slots", [])
               if s.get("d") == day1 and s.get("t", "") < first and (s["d"], s["t"]) not in have]
        if add:
            p["slots"] = sorted(add + S, key=lambda s: (s["d"], s["t"]))
            print("historie:", pid, [s["t"] for s in add])

    validate(data)
    tmp = DATA.with_suffix(".new.json")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "scripts" / "note.js"), str(ROOT / "index.html"), str(tmp)], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode:
        print("POZOR: komentář se nepovedl:", r.stderr[:600])
    tmp.replace(DATA)
    print("OK", data["issued"], {k: len(v["slots"]) for k, v in data["points"].items()}, {k: len(v) for k, v in data["tides"].items()})


if __name__ == "__main__":
    main()
