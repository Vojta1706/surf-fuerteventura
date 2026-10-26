// Napíše krátký komentář (note česky, noteEn anglicky) k nové předpovědi.
// Bere výpočty přímo ze stránky (index.html), takže okna a skóre sedí s tím, co stránka ukazuje.
//   node scripts/note.js index.html data/forecast.json
const fs = require("fs"), os = require("os"), path = require("path");
const [pagePath, dataPath] = process.argv.slice(2);
const html = fs.readFileSync(pagePath, "utf8");
const main = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).find(s => s.includes("const SPOTS"));
const cut = main.indexOf("// ---- UI layer");
const tmp = path.join(os.tmpdir(), "surf-core.js");
fs.writeFileSync(tmp, cut > 0 ? main.slice(0, cut) : main);
const C = require(tmp);
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
const TS = Object.fromEntries(Object.entries(data.tides).map(([k, v]) => [k, C.prepTides(v)]));

const DAY_CZ = ["neděle", "pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota"];
const DAY_EN = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const WIND_CZ = {glassy: "bezvětří", off: "vítr od břehu", crossoff: "boční vítr od břehu", cross: "boční vítr", crosson: "boční vítr ke břehu", on: "vítr ke břehu", unknown: "vítr ?"};
const WIND_EN = {glassy: "glassy", off: "offshore wind", crossoff: "cross-offshore wind", cross: "cross-shore wind", crosson: "cross-onshore wind", on: "onshore wind", unknown: "wind ?"};
const wd = d => new Date(d + "T12:00:00Z").getUTCDay();
const dateCz = d => `${+d.slice(8)}. ${+d.slice(5, 7)}.`;
const cap = s => s[0].toUpperCase() + s.slice(1);
const mCz = h => h.toFixed(1).replace(".", ",");

const now = Date.now();
const days = [...new Set(Object.values(data.points).flatMap(p => p.slots.map(s => s.d)))].sort().slice(0, 3);

function best(d, lvl) {
  const out = [];
  for (const sp of C.SPOTS) {
    const p = data.points[sp.point]; if (!p) continue;
    const S = C.prepSlots(p.slots), T = TS[p.tides] || [];
    const sc = C.dayScores(sp, S, T, d, lvl);
    const W = C.rideWindows(sp, S, T, d, 3, sc, lvl).filter(w => w.b > now);
    for (const w of W) out.push({sp, w});
    if (!W.length) { const st = C.bestStretch(sc, now); if (st) out.push({sp, w: st, weak: true}); }
  }
  return out.sort((a, b) => (b.w.v - a.w.v) || ((b.w.coreB - b.w.coreA) - (a.w.coreB - a.w.coreA)));
}

const cz = [], en = [];
for (const d of days) {
  const all = best(d, "int").filter(x => x.w && x.w.v != null);
  if (!all.length) continue;
  const top = all[0];
  const dayCz = `${cap(DAY_CZ[wd(d)])} ${dateCz(d)}`, dayEn = `${DAY_EN[wd(d)]}`;
  const span = x => `${C.hm(x.w.coreA ?? x.w.a)}–${C.hm(x.w.coreB ?? x.w.b)}`;
  const why = (x, L) => x.w.cond ? `${L === "cz" ? mCz(x.w.cond.h) : x.w.cond.h.toFixed(1)} m, ${(L === "cz" ? WIND_CZ : WIND_EN)[x.w.wind ? x.w.wind.k : "unknown"]}` : "";
  if (top.w.v < 3 || top.weak) {
    cz.push(`${dayCz}: slabé, nejvýš ${top.sp.name} ${span(top)} (${top.w.v}/10; ${why(top, "cz")}).`);
    en.push(`${dayEn}: weak, at best ${top.sp.name} ${span(top)} (${top.w.v}/10; ${why(top, "en")}).`);
    continue;
  }
  // Nejlepší spot dne a k tomu nejlepší z jiného regionu, pokud stojí za to.
  const other = all.find(x => !x.weak && x.sp.region !== top.sp.region && x.w.v >= 6);
  let sCz = `${dayCz}: nejlíp ${top.sp.name} ${span(top)} (${top.w.v}/10; ${why(top, "cz")})`;
  let sEn = `${dayEn}: best is ${top.sp.name} ${span(top)} (${top.w.v}/10; ${why(top, "en")})`;
  if (other) { sCz += `, dál ${other.sp.name} ${span(other)} (${other.w.v}/10)`; sEn += `, then ${other.sp.name} ${span(other)} (${other.w.v}/10)`; }
  cz.push(sCz + "."); en.push(sEn + ".");
}
// Začátečníci: nejlepší okno pro začátečníky, když nějaké je aspoň 6/10.
let beg = null;
for (const d of days) { const b = best(d, "beg").find(x => !x.weak && x.w.v >= 6); if (b && (!beg || b.w.v > beg.x.w.v)) beg = {d, x: b}; }
if (beg) {
  const s = `${C.hm(beg.x.w.coreA)}–${C.hm(beg.x.w.coreB)}`;
  cz.push(`Začátečníkům nejvíc sedne ${beg.x.sp.name} (${DAY_CZ[wd(beg.d)]} ${s}, ${beg.x.w.v}/10).`);
  en.push(`For beginners, ${beg.x.sp.name} suits best (${DAY_EN[wd(beg.d)]} ${s}, ${beg.x.w.v}/10).`);
}
data.note = cz.join(" ");
data.noteEn = en.join(" ");
fs.writeFileSync(dataPath, JSON.stringify(data, null, 1));
console.log("note:", data.note);
