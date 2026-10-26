# Surf Fuerteventura

Surfová předpověď pro severní Fuerteventuru (Punta Blanca, Majanicho, La Caleta, Dunas, Rocky Point, Playa de Esquinzo) pro středně pokročilé a začátečníky.

- **Stránka:** `index.html`, běží na GitHub Pages. Data si načítá ze souboru `data/forecast.json` a skóre, okna i hodnocení počítá sama v prohlížeči.
- **Aktualizace:** GitHub Action `.github/workflows/update.yml` se spouští každých 15 minut. Skript `scripts/update.py` se podívá, jestli má surf-forecast.com novější předpověď. Pokud ano, stáhne ji i s přílivy, zkontroluje ji, nechá `scripts/note.js` napsat krátký komentář a uloží nová data.
- **Ruční spuštění:** záložka Actions → Aktualizace předpovědi → Run workflow. Režim `force` uloží data i bez nové předpovědi, `debug` jen vypíše, co skript ze stránek přečetl.

Data pocházejí ze surf-forecast.com. Repozitář je jen pro osobní potřebu.
