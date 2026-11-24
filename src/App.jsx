import { useState, useEffect, useMemo, useCallback } from "react";

/* ──────────────────────────────────────────────────────────────────────
   CONSTANTS
────────────────────────────────────────────────────────────────────── */

const FIGURES_JSON_URL = "./figures.json";
const META_JSON_URL    = "./meta.json";
const YEAR_MIN = 2007;
// Upper bound of the year filter; leaves room for announced pre-orders.
const YEAR_MAX = new Date().getFullYear() + 2;
const SCRAPE_WORKFLOW_URL = "https://github.com/TheBooleanJulian/miku-figures/actions/workflows/daily_scrape.yml";

// Retailers the daily scrape checks. `id` matches each row's `source`.
const VENDORS = [
  { id: "hlj",     name: "HobbyLink Japan", site: "hlj.com",          url: "https://www.hlj.com",           currency: "SGD", note: "Search listings, then product pages" },
  { id: "solaris", name: "Solaris Japan",   site: "solarisjapan.com", url: "https://solarisjapan.com",      currency: "USD", note: "Figures HLJ lacks; JAN duplicates skipped" },
  { id: "latendo", name: "Latendo",         site: "latendo.com",      url: "https://www.latendo.com/shop",  currency: "SGD", note: "Sitemap + product pages; name duplicates skipped" },
  { id: "ninnin",  name: "Nin-Nin-Game",    site: "nin-nin-game.com", url: "https://www.nin-nin-game.com/en/", currency: "USD", note: "Sitemap + product pages, incl. 2nd hand; JAN duplicates skipped" },
  { id: "gsc",     name: "Good Smile Company", site: "goodsmile.com", url: "https://www.goodsmile.com/en",  currency: "JPY", note: "Official catalogue; JAN duplicates skipped" },
  { id: "mfl",     name: "MyFigureList",    site: "myfigurelist.com", url: "https://myfigurelist.com",      currency: "JPY", note: "Figure database, lowest shop price; fills gaps, JAN duplicates skipped" },
];
const vendorOf = id => VENDORS.find(v => v.id === id);

const TYPE_ORDER = [
  "Scale", "Nendoroid", "Pop Up Parade", "Figma",
  "Prize", "Mini / Petite", "Plush / Soft", "Doll / BJD",
  "Bust", "Garage Kit", "Other",
];

const SORT_OPTIONS = [
  { value: "date-desc",  label: "Newest first" },
  { value: "date-asc",   label: "Oldest first" },
  { value: "name-asc",   label: "Name A → Z" },
  { value: "name-desc",  label: "Name Z → A" },
  { value: "maker-asc",  label: "Maker A → Z" },
  { value: "price-desc", label: "Price high → low" },
  { value: "price-asc",  label: "Price low → high" },
];

/* ──────────────────────────────────────────────────────────────────────
   SAMPLE FALLBACK DATA  (shown when figures.json can't be loaded)
────────────────────────────────────────────────────────────────────── */
const DEMO_FIGURES = Array.from({ length: 24 }, (_, i) => {
  const events = ["Snow Miku", "Racing Miku", "Sakura Miku", "Magical Mirai", "Symphony"];
  const makers = ["Good Smile Company", "Taito", "Max Factory", "Kotobukiya", "Alter", "FuRyu", "SEGA"];
  const year   = 2007 + (i * 7) % 19;
  const type   = TYPE_ORDER[i % TYPE_ORDER.length];
  const event  = i % 3 ? [events[i % events.length]] : [];
  const maker  = makers[i % makers.length];
  return {
    id: `demo-${i}`,
    name: `Hatsune Miku ${event[0] || ""} ${year} Ver.`.replace(/\s+/g, " "),
    manufacturer: maker,
    release_date: `${year}-${String((i % 12) + 1).padStart(2, "0")}`,
    year, type,
    scale: type === "Scale" ? `1/${[4, 6, 7, 8][i % 4]}` : null,
    price_sgd: type === "Prize" ? null : [55, 64, 130, 165, 198, 242][i % 6],
    image_url: null, events: event, illustrator: null,
    tags: [type, ...event, maker], source: VENDORS[i % VENDORS.length].id,
  };
});

/* ──────────────────────────────────────────────────────────────────────
   HELPERS
────────────────────────────────────────────────────────────────────── */

function fmtSGD(n) {
  if (!n) return null;
  return new Intl.NumberFormat("en-SG", { style: "currency", currency: "SGD" }).format(n);
}

// Approximate rate, used only to sort/filter USD-priced rows alongside SGD ones.
const USD_TO_SGD = 1.3;
const JPY_TO_SGD = 0.0088;
const priceSGD = f => f.price_sgd || (f.price_usd ? f.price_usd * USD_TO_SGD : f.price_jpy ? f.price_jpy * JPY_TO_SGD : null);

// Price for display: SGD when the vendor gave one (HLJ, Latendo), else USD (Solaris,
// Nin-Nin-Game), else JPY (Good Smile Company's retail price).
function fmtPrice(fig) {
  if (fig.price_sgd) return fmtSGD(fig.price_sgd);
  if (fig.price_usd) return "US" + new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(fig.price_usd);
  if (fig.price_jpy) return "¥" + new Intl.NumberFormat("en-US").format(fig.price_jpy);
  return null;
}

function sortFigures(list, mode) {
  return [...list].sort((a, b) => {
    switch (mode) {
      case "date-desc":  return (b.release_date || "0").localeCompare(a.release_date || "0");
      case "date-asc":   return (a.release_date || "9").localeCompare(b.release_date || "9");
      case "name-asc":   return a.name.localeCompare(b.name);
      case "name-desc":  return b.name.localeCompare(a.name);
      case "maker-asc":  return (a.manufacturer || "").localeCompare(b.manufacturer || "");
      case "price-desc": return (priceSGD(b) || 0) - (priceSGD(a) || 0);
      case "price-asc":  return (priceSGD(a) || Infinity) - (priceSGD(b) || Infinity);
      default: return 0;
    }
  });
}

// "2026-11" for the current month; releases from this month on count as upcoming.
const THIS_MONTH = new Date().toISOString().slice(0, 7);
const isUpcoming = f => (f.release_date || "") >= THIS_MONTH;
const PRICE_PRESETS = [50, 100, 200, 500];

function monthLabel(ym) {
  if (!ym) return "Release date unknown";
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, (m || 1) - 1, 1).toLocaleDateString("en-SG", { month: "long", year: "numeric" });
}

// Figures grouped by release month, newest month first (oldest first when `asc`),
// unknown dates last. Order within a month is kept.
function groupByMonth(list, asc) {
  const m = new Map();
  list.forEach(f => {
    const k = (f.release_date || "").slice(0, 7);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(f);
  });
  return [...m.entries()].sort(([a], [b]) => (!a) - (!b) || (asc ? a.localeCompare(b) : b.localeCompare(a)));
}

// Count values across figures, most common first.
function countBy(figures, pick) {
  const m = new Map();
  figures.forEach(f => [].concat(pick(f) || []).forEach(v => m.set(v, (m.get(v) || 0) + 1)));
  return [...m.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
}

// Enter/Space activates a clickable non-button element.
const onActivate = fn => e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } };

/* ──────────────────────────────────────────────────────────────────────
   THEME
────────────────────────────────────────────────────────────────────── */

function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function ThemeToggle() {
  const [theme, setTheme] = useState(currentTheme);
  const next = theme === "dark" ? "light" : "dark";
  const toggle = () => {
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* private mode: choice lasts this visit */ }
    setTheme(next);
  };
  return (
    <button className="btn btn--ghost" onClick={toggle} aria-label={`Switch to ${next} theme`}>
      {next === "light" ? "Light" : "Dark"}
    </button>
  );
}

/* ──────────────────────────────────────────────────────────────────────
   SUB-COMPONENTS
────────────────────────────────────────────────────────────────────── */

function ImageIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21" />
    </svg>
  );
}

function Thumbnail({ src, name, fit = "cover" }) {
  const [err, setErr] = useState(false);
  if (!src || err) {
    return (
      <div className="thumb-empty">
        <ImageIcon />
        <span className="mono-sm">No image</span>
      </div>
    );
  }
  return (
    <img src={src} alt={name} loading="lazy" onError={() => setErr(true)}
      style={{ width: "100%", height: "100%", objectFit: fit }} />
  );
}

function FigureCard({ fig, onOpen }) {
  const open = () => onOpen(fig);
  return (
    <article className="card" tabIndex={0} role="button" aria-label={fig.name}
      onClick={open} onKeyDown={onActivate(open)}>
      <div className="card__img">
        <Thumbnail src={fig.image_url} name={fig.name} />
        <span className="badge badge--sm card__type">{fig.type}</span>
        <span className="mono-sm card__year">{fig.year || "—"}</span>
        {fig.events?.length > 0 && (
          <div className="card__events">
            {fig.events.slice(0, 2).map(ev => <span key={ev}>{ev}</span>)}
          </div>
        )}
      </div>
      <div className="card__body">
        <div className="card__name">{fig.name}</div>
        <div className="card__meta">
          <span className="card__maker">{fig.manufacturer || "—"}</span>
          <span className="mono-sm card__price">{fig.scale || fmtPrice(fig) || ""}</span>
        </div>
      </div>
    </article>
  );
}

function FigureRow({ fig, onOpen }) {
  const open = () => onOpen(fig);
  return (
    <div className="row" tabIndex={0} role="button" aria-label={fig.name}
      onClick={open} onKeyDown={onActivate(open)}>
      <div className="row__img"><Thumbnail src={fig.image_url} name={fig.name} /></div>
      <div className="row__main">
        <div className="row__name">{fig.name}</div>
        <div className="row__sub">
          {fig.manufacturer}{fig.illustrator ? ` · ${fig.illustrator}` : ""}
          {vendorOf(fig.source) ? ` · ${vendorOf(fig.source).name}` : ""}
        </div>
      </div>
      <span className="badge badge--sm">{fig.type}</span>
      <span className="mono-sm row__col row__year">{fig.year || "—"}</span>
      <span className="mono-sm row__col row__scale">{fig.scale || ""}</span>
      <span className="mono-sm row__col row__price">{fmtPrice(fig) || "—"}</span>
    </div>
  );
}

function DetailModal({ fig, onClose }) {
  useEffect(() => {
    const handler = e => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const vendor = vendorOf(fig.source);
  const specs = [
    { label: "Manufacturer", value: fig.manufacturer },
    { label: "Release date", value: fig.release_date, mono: true },
    { label: "Type",         value: fig.type },
    { label: "Scale",        value: fig.scale, mono: true },
    { label: "Price",        value: fmtPrice(fig), mono: true },
    { label: "Illustrator",  value: fig.illustrator },
    { label: "Dimensions",   value: fig.dimensions, mono: true },
    { label: "Material",     value: fig.material },
    { label: "JAN code",     value: fig.barcode, mono: true },
    { label: "Vendor",       value: vendor?.name },
  ].filter(s => s.value);

  return (
    <div className="scrim" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title"
        onClick={e => e.stopPropagation()}>
        <button className="btn btn--sm dialog__close" onClick={onClose} autoFocus>Close</button>

        {/* Portrait image panel; contained so the figure is never cropped */}
        <div className={`dialog__img${fig.image_url ? "" : " dialog__img--empty"}`}>
          <div className="dialog__img-inner">
            <Thumbnail src={fig.image_url} name={fig.name} fit="contain" />
          </div>
          <span className="badge">{fig.type}</span>
        </div>

        <div className="dialog__body">
          <h2 id="dialog-title" className="dialog__title">{fig.name}</h2>

          <div className="specs">
            {specs.map(s => (
              <div key={s.label} className="panel panel--raised">
                <div className="panel__title">{s.label}</div>
                <div className={`spec__value ${s.mono ? "mono" : ""}`}>{s.value}</div>
              </div>
            ))}
          </div>

          {fig.events?.length > 0 && (
            <div className="dialog__section">
              <div className="panel__title">Series / event</div>
              <div className="filter__chips">
                {fig.events.map(ev => <span key={ev} className="badge badge--cyan">{ev}</span>)}
              </div>
            </div>
          )}

          {fig.tags?.length > 0 && (
            <div className="dialog__section">
              <div className="panel__title">Tags</div>
              <div className="filter__chips">
                {[...new Set(fig.tags)].map(t => <span key={t} className="badge">{t}</span>)}
              </div>
            </div>
          )}

          {fig.description && <p className="dialog__desc">{fig.description}</p>}

          {fig.detail_url && (
            <a className="btn btn--primary dialog__link" href={fig.detail_url} target="_blank" rel="noopener noreferrer">
              View on {vendor?.name || "vendor"} ↗
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function FilterSection({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="filter">
      <button className="filter__head label" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        {title}
        <span aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open && children}
    </section>
  );
}

// Long lists show the biggest `limit` entries (plus anything selected) until expanded.
function ChipFilter({ entries, selected, onToggle, limit = Infinity }) {
  const [all, setAll] = useState(false);
  const shown = all ? entries : entries.filter(([v], i) => i < limit || selected.includes(v));
  return (
    <div className="filter__chips">
      {shown.map(([value, count]) => (
        <button key={value} className="chip" aria-pressed={selected.includes(value)} onClick={() => onToggle(value)}>
          {value}<span className="chip__count">{count}</span>
        </button>
      ))}
      {entries.length > limit && (
        <button className="chip chip--more" onClick={() => setAll(a => !a)}>
          {all ? "Show fewer" : `+${entries.length - shown.length} more`}
        </button>
      )}
    </div>
  );
}

// Footer: where the data comes from, collapsed so shoppers aren't greeted by a data table.
function VendorsPanel({ figures, meta }) {
  const counts = Object.fromEntries(countBy(figures, f => f.source));
  return (
    <details className="panel about">
      <summary className="about__summary">
        <span className="label">About this archive</span>
        <span className="muted">Collected daily from {VENDORS.length} shops and databases</span>
      </summary>
      <p className="about__text">
        Prices and links come from the shops below and are refreshed every morning.
        Click any figure to see where it's sold.
      </p>
      <table className="table vendors__table">
        <thead>
          <tr><th>Source</th><th className="num">Figures</th><th>Prices in</th><th className="vendors__note">Notes</th></tr>
        </thead>
        <tbody>
          {VENDORS.map(v => (
            <tr key={v.id}>
              <td className="vendors__name">
                <a href={v.url} target="_blank" rel="noopener noreferrer">{v.name}</a>
                <span>{v.site}</span>
              </td>
              <td className="num">{(counts[v.id] || 0).toLocaleString()}</td>
              <td>{v.currency}</td>
              <td className="vendors__note">{v.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="vendors__foot">
        Checked every day at <span className="mono-sm">03:00 SGT</span>
        {meta?.last_updated && <> · last run <span className="mono-sm">{new Date(meta.last_updated).toLocaleString("en-SG", { dateStyle: "medium", timeStyle: "short", hour12: false })}</span></>}
        {" · "}<a href={SCRAPE_WORKFLOW_URL} target="_blank" rel="noopener noreferrer">Update log ↗</a>
      </p>
    </details>
  );
}

// Browse shortcuts shown above the results while no filter is set: the biggest
// categories and themes with their counts, plus quick picks.
function Item({ label, count, onClick, sub }) {
  return (
    <li>
      <button className="explore__item" onClick={onClick}>
        <span className="explore__label">{label}{sub && <span className="explore__sub">{sub}</span>}</span>
        {count != null && <span className="chip__count">{count.toLocaleString()}</span>}
      </button>
    </li>
  );
}

function ExplorePanel({ types, themes, upcomingCount, onType, onTheme, onPick, onHide }) {
  return (
    <section className="panel explore" aria-labelledby="explore-title">
      <h2 id="explore-title" className="panel__title">
        Explore
        <button className="btn btn--sm btn--ghost" onClick={onHide}>Hide</button>
      </h2>
      <div className="explore__cols">
        <div>
          <div className="label explore__head">By category</div>
          <ul>{types.map(([t, n]) => <Item key={t} label={t} count={n} onClick={() => onType(t)} />)}</ul>
        </div>
        <div>
          <div className="label explore__head">By theme</div>
          <ul>{themes.map(([t, n]) => <Item key={t} label={t} count={n} onClick={() => onTheme(t)} />)}</ul>
        </div>
        <div>
          <div className="label explore__head">Browse</div>
          <ul>
            <Item label="Release calendar" sub="Upcoming, by month" count={upcomingCount} onClick={() => onPick("calendar")} />
            <Item label="Newest" sub="Latest releases first" onClick={() => onPick("newest")} />
            <Item label="Cheapest first" sub="Price low to high" onClick={() => onPick("cheapest")} />
            <Item label="Under S$50" sub="Prizes, minis, plushes" onClick={() => onPick("under50")} />
          </ul>
        </div>
      </div>
    </section>
  );
}

function readPref(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function writePref(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage blocked: keep in memory only */ }
}

/* ──────────────────────────────────────────────────────────────────────
   MAIN APP
────────────────────────────────────────────────────────────────────── */

export default function MikuFigureArchive() {
  const [figures, setFigures]     = useState([]);
  const [meta, setMeta]           = useState(null);
  const [loading, setLoading]     = useState(true);
  const [usingDemo, setUsingDemo] = useState(false);

  // Filters
  const [search, setSearch]                 = useState("");
  const [typeFilter, setTypeFilter]         = useState("All");
  const [eventFilters, setEventFilters]     = useState([]);
  const [illustratorFilters, setIllFilters] = useState([]);
  const [makerFilter, setMakerFilter]       = useState("All");
  const [yearFrom, setYearFrom]             = useState(YEAR_MIN);
  const [yearTo, setYearTo]                 = useState(YEAR_MAX);
  const [priceMax, setPriceMax]             = useState("");
  const [upcoming, setUpcoming]             = useState(false);
  const [sortBy, setSortBy]                 = useState("date-desc");
  const [viewMode, setViewMode]             = useState("grid");
  const [exploreOpen, setExploreOpen]       = useState(() => readPref("explore", "open") === "open");
  const [selected, setSelected]             = useState(null);
  const [filtersOpen, setFiltersOpen]       = useState(false);   // narrow screens only

  /* ── Load data ── */
  useEffect(() => {
    async function load() {
      try {
        const [figRes, metaRes] = await Promise.all([
          fetch(FIGURES_JSON_URL),
          fetch(META_JSON_URL).catch(() => null),
        ]);
        if (!figRes.ok) throw new Error("figures.json not found");
        setFigures(await figRes.json());
        if (metaRes?.ok) setMeta(await metaRes.json());
      } catch {
        // Fall back to demo data so the UI is always usable
        setFigures(DEMO_FIGURES);
        setUsingDemo(true);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  /* ── Filter options, built from the data ── */
  const allMakers  = useMemo(() => ["All", ...[...new Set(figures.map(f => f.manufacturer).filter(Boolean))].sort()], [figures]);
  const typeCounts = useMemo(() => Object.fromEntries(countBy(figures, f => f.type)), [figures]);
  const eventList  = useMemo(() => countBy(figures, f => f.events), [figures]);
  const illList    = useMemo(() => countBy(figures, f => f.illustrator), [figures]);
  const upcomingCount = useMemo(() => figures.filter(isUpcoming).length, [figures]);

  /* ── Filtered + sorted list ── */
  const filtered = useMemo(() => {
    let list = figures;
    const q = search.trim().toLowerCase();
    if (q) list = list.filter(f =>
      f.name.toLowerCase().includes(q) ||
      (f.manufacturer || "").toLowerCase().includes(q) ||
      f.tags?.some(t => t.toLowerCase().includes(q))
    );
    if (typeFilter !== "All") list = list.filter(f => f.type === typeFilter);
    if (makerFilter !== "All") list = list.filter(f => f.manufacturer === makerFilter);
    if (eventFilters.length)  list = list.filter(f => eventFilters.some(ev => f.events?.includes(ev)));
    if (illustratorFilters.length) list = list.filter(f => illustratorFilters.includes(f.illustrator));
    list = list.filter(f => !f.year || (f.year >= yearFrom && f.year <= yearTo));   // unknown year: never hide
    if (upcoming) list = list.filter(isUpcoming);
    if (priceMax !== "") {
      const max = parseInt(priceMax);
      list = list.filter(f => !priceSGD(f) || priceSGD(f) <= max);
    }
    return sortFigures(list, sortBy);
  }, [figures, search, typeFilter, makerFilter, eventFilters, illustratorFilters, yearFrom, yearTo, upcoming, priceMax, sortBy]);

  const months = useMemo(() => viewMode === "calendar" ? groupByMonth(filtered, sortBy === "date-asc") : [],
    [viewMode, filtered, sortBy]);

  const toggleEvent = useCallback(ev => setEventFilters(p => p.includes(ev) ? p.filter(x => x !== ev) : [...p, ev]), []);
  const toggleIll   = useCallback(il => setIllFilters(p => p.includes(il) ? p.filter(x => x !== il) : [...p, il]), []);

  const clearAll = useCallback(() => {
    setSearch(""); setTypeFilter("All"); setEventFilters([]); setIllFilters([]);
    setMakerFilter("All"); setYearFrom(YEAR_MIN); setYearTo(YEAR_MAX); setPriceMax(""); setUpcoming(false);
  }, []);

  const hasFilters = search || typeFilter !== "All" || eventFilters.length || illustratorFilters.length ||
    makerFilter !== "All" || yearFrom > YEAR_MIN || yearTo < YEAR_MAX || priceMax !== "" || upcoming;

  const setExplore = useCallback(open => { setExploreOpen(open); writePref("explore", open ? "open" : "hidden"); }, []);
  const explorePick = useCallback(pick => {
    if (pick === "calendar") { setUpcoming(true); setSortBy("date-asc"); setViewMode("calendar"); }
    if (pick === "newest")   setSortBy("date-desc");
    if (pick === "cheapest") setSortBy("price-asc");
    if (pick === "under50")  { setPriceMax("50"); setSortBy("price-asc"); }
  }, []);
  const exploreTypes  = useMemo(() => TYPE_ORDER.filter(t => typeCounts[t]).map(t => [t, typeCounts[t]])
    .sort((a, b) => b[1] - a[1]).slice(0, 6), [typeCounts]);
  const exploreThemes = useMemo(() => eventList.slice(0, 6), [eventList]);

  /* ── LOADING STATE ── */
  if (loading) return (
    <div className="loading" role="status">
      <div className="loading__track"><div className="loading__fill signal" /></div>
      <div>Loading figure archive</div>
    </div>
  );

  /* ── MAIN RENDER ── */
  return (
    <>
      {/* ── HEADER ── */}
      <header className="app-head">
        <div className="app-head__inner">
          <div className="app-head__top">
            <div className="brand">
              <img src="/logo.png" alt="" className="brand__logo" />
              <div>
                <h1 className="brand__title">Miku Figures</h1>
                <div className="brand__sub">
                  {figures.length.toLocaleString()} Hatsune Miku figures, plushes and prizes
                  {meta?.last_updated && <> · updated {new Date(meta.last_updated).toLocaleDateString("en-SG", { dateStyle: "medium" })}</>}
                </div>
              </div>
            </div>
            <ThemeToggle />
          </div>

          {usingDemo && (
            <div className="alert alert--warning" role="status">
              <span className="alert__icon" aria-hidden="true">!</span>
              <div>
                <div className="alert__title">Showing sample figures</div>
                <div className="alert__body">The figure list couldn't be loaded. Try refreshing in a minute.</div>
              </div>
            </div>
          )}
        </div>
        <div className="hairline signal" />
      </header>

      {/* ── BODY ── */}
      <div className="layout">

        {/* ── SIDEBAR ── */}
        <aside id="filters" className={`sidebar${filtersOpen ? " sidebar--open" : ""}`} aria-label="Filters">
          {hasFilters && (
            <div className="filter">
              <button className="btn btn--sm" style={{ width: "100%" }} onClick={clearAll}>Clear filters</button>
            </div>
          )}

          <FilterSection title="Type">
            <div className="typelist">
              {["All", ...TYPE_ORDER].map(t => {
                const count = t === "All" ? figures.length : (typeCounts[t] || 0);
                return count > 0 ? (
                  <button key={t} aria-pressed={typeFilter === t} onClick={() => setTypeFilter(t)}>
                    <span>{t}</span><span className="chip__count">{count}</span>
                  </button>
                ) : null;
              })}
            </div>
          </FilterSection>

          {eventList.length > 0 && (
            <FilterSection title="Theme">
              <ChipFilter entries={eventList} selected={eventFilters} onToggle={toggleEvent} limit={10} />
            </FilterSection>
          )}

          <FilterSection title="Price">
            <div className="filter__chips">
              {PRICE_PRESETS.map(p => (
                <button key={p} className="chip" aria-pressed={priceMax === String(p)}
                  onClick={() => setPriceMax(priceMax === String(p) ? "" : String(p))}>Under S${p}</button>
              ))}
            </div>
          </FilterSection>

          <FilterSection title="Release">
            <div className="filter__chips">
              <button className="chip" aria-pressed={upcoming} onClick={() => setUpcoming(u => !u)}>
                Upcoming<span className="chip__count">{upcomingCount}</span>
              </button>
            </div>
            <div className="filter__range filter__extra">
              <input className="input input--mono" type="number" value={yearFrom} min={YEAR_MIN} max={yearTo}
                onChange={e => setYearFrom(+e.target.value)} aria-label="From year" />
              <span className="muted">to</span>
              <input className="input input--mono" type="number" value={yearTo} min={yearFrom} max={YEAR_MAX}
                onChange={e => setYearTo(+e.target.value)} aria-label="To year" />
            </div>
          </FilterSection>

          <FilterSection title="Maker">
            <select className="input" value={makerFilter} onChange={e => setMakerFilter(e.target.value)} aria-label="Maker">
              {allMakers.map(m => <option key={m} value={m}>{m === "All" ? "Any maker" : m}</option>)}
            </select>
          </FilterSection>

          {illList.length > 0 && (
            <FilterSection title="Artist" defaultOpen={illustratorFilters.length > 0}>
              <ChipFilter entries={illList} selected={illustratorFilters} onToggle={toggleIll} limit={8} />
            </FilterSection>
          )}
        </aside>

        {/* ── MAIN CONTENT ── */}
        <main className="content">
          <div className="toolbar">
            <div className="toolbar__search">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
              </svg>
              <input className="input input--lg" placeholder="Search figures, makers, tags" value={search}
                onChange={e => setSearch(e.target.value)} aria-label="Search" />
            </div>
            <button className="btn toolbar__filters" aria-expanded={filtersOpen} aria-controls="filters"
              onClick={() => setFiltersOpen(o => !o)}>
              {filtersOpen ? "Hide filters" : "Filters"}
            </button>
            <select className="input" value={sortBy} onChange={e => setSortBy(e.target.value)} aria-label="Sort">
              {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <div className="segmented" role="group" aria-label="View">
              {[["grid", "Grid"], ["list", "List"], ["calendar", "Calendar"]].map(([mode, label]) => (
                <button key={mode} className="btn" aria-pressed={viewMode === mode} onClick={() => setViewMode(mode)}>{label}</button>
              ))}
            </div>
          </div>

          {!hasFilters && (exploreOpen ? (
            <ExplorePanel types={exploreTypes} themes={exploreThemes} upcomingCount={upcomingCount}
              onType={setTypeFilter} onTheme={toggleEvent} onPick={explorePick} onHide={() => setExplore(false)} />
          ) : (
            <button className="btn btn--sm btn--ghost explore__show" onClick={() => setExplore(true)}>Show explore</button>
          ))}

          <div className="resultline">
            <span><strong className="mono">{filtered.length}</strong> of <span className="mono">{figures.length}</span> figures</span>
            {upcoming && (
              <button className="chip" aria-pressed="true" onClick={() => setUpcoming(false)}>Upcoming ×</button>
            )}
            {eventFilters.map(tag => (
              <button key={tag} className="chip" aria-pressed="true" onClick={() => toggleEvent(tag)}>{tag} ×</button>
            ))}
            {illustratorFilters.map(tag => (
              <button key={tag} className="chip" aria-pressed="true" onClick={() => toggleIll(tag)}>{tag} ×</button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="empty">
              <div className="empty__title">No figures found</div>
              <div>Try fewer filters.</div>
            </div>
          ) : viewMode === "grid" ? (
            <div className="grid">
              {filtered.map(fig => <FigureCard key={fig.id} fig={fig} onOpen={setSelected} />)}
            </div>
          ) : viewMode === "calendar" ? (
            <div className="calendar">
              {months.map(([ym, figs]) => (
                <section key={ym || "unknown"} className="calendar__month" aria-label={monthLabel(ym)}>
                  <h3 className="calendar__head">
                    <span>{monthLabel(ym)}</span>
                    <span className="chip__count">{figs.length}</span>
                  </h3>
                  <div className="grid">
                    {figs.map(fig => <FigureCard key={fig.id} fig={fig} onOpen={setSelected} />)}
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <div className="list">
              {filtered.map(fig => <FigureRow key={fig.id} fig={fig} onOpen={setSelected} />)}
            </div>
          )}
        </main>
      </div>

      <footer className="app-foot">
        <VendorsPanel figures={figures} meta={meta} />
      </footer>

      {selected &&<DetailModal fig={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
