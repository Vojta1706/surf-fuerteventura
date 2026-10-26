"""Ladění: stáhne stránky surf-forecastu a uloží je do složky debug/ i se stavovým kódem."""
import pathlib, time, requests
out = pathlib.Path("debug"); out.mkdir(exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept-Language": "en-GB,en;q=0.9", "Accept": "text/html,application/xhtml+xml"}
B = "https://www.surf-forecast.com/breaks/"
pages = {"esquinzo": B + "Playade-Esquinzo_1/forecasts/latest?units=m", "majanicho_tides": B + "Majanicho/tides/latest",
         "esquinzo_tides": B + "Playade-Esquinzo_1/tides/latest"}
log = []
for name, url in pages.items():
    try:
        r = requests.get(url, headers=H, timeout=40)
        (out / f"{name}.html").write_text(r.text, encoding="utf-8")
        log.append(f"{name}: {r.status_code} {len(r.text)} B {dict(list(r.headers.items())[:12])}")
    except Exception as e:
        log.append(f"{name}: {e!r}")
    time.sleep(2)
(out / "log.txt").write_text("\n".join(log), encoding="utf-8")
print("\n".join(log))
