import { useState, useEffect, useMemo, useCallback, useRef } from "react";

/* ──────────────────────────────────────────────────────────────────────
   CONSTANTS
────────────────────────────────────────────────────────────────────── */

// In production point this to your GitHub raw URL or Vercel public path
const FIGURES_JSON_URL = "./figures.json";
const META_JSON_URL    = "./meta.json";

const TYPE_ORDER = [
  "Scale", "Nendoroid", "Pop Up Parade", "Figma",
  "Prize", "Mini / Petite", "Plush / Soft", "Doll / BJD",
  "Bust", "Garage Kit", "Other",
];

const EVENT_ORDER = [
  "Snow Miku", "Racing Miku", "Magical Mirai", "Symphony",
  "Append", "EXPO", "Deep Sea Girl", "BEAST RINGER",
  "World is Mine", "Senbonzakura", "Tell Your World",
  "Sand Planet", "Mikudayo", "Live Stage",
];

const ILLUSTRATOR_ORDER = [
  "KEI", "Rella", "iXima", "Fuzichoco", "GEMI",
  "Saine", "Ontama", "Yunomachi", "raemz", "azurite",
];

const SORT_OPTIONS = [
  { value: "date-desc",  label: "Newest First" },
  { value: "date-asc",   label: "Oldest First" },
  { value: "name-asc",   label: "Name A → Z" },
  { value: "name-desc",  label: "Name Z → A" },
  { value: "maker-asc",  label: "Maker A → Z" },
  { value: "price-desc", label: "Price ↓" },
  { value: "price-asc",  label: "Price ↑" },
];

const TYPE_PALETTE = {
  "Scale":          { bg: "#00e5ff", glow: "rgba(0,229,255,0.35)" },
  "Nendoroid":      { bg: "#ff79c6", glow: "rgba(255,121,198,0.35)" },
  "Pop Up Parade":  { bg: "#ff9f43", glow: "rgba(255,159,67,0.35)" },
  "Figma":          { bg: "#54a0ff", glow: "rgba(84,160,255,0.35)" },
  "Prize":          { bg: "#5f27cd", glow: "rgba(95,39,205,0.35)" },
  "Mini / Petite":  { bg: "#a9dc76", glow: "rgba(169,220,118,0.35)" },
  "Plush / Soft":   { bg: "#fd79a8", glow: "rgba(253,121,168,0.35)" },
  "Doll / BJD":     { bg: "#e17055", glow: "rgba(225,112,85,0.35)" },
  "Bust":           { bg: "#fdcb6e", glow: "rgba(253,203,110,0.35)" },
  "Garage Kit":     { bg: "#6c5ce7", glow: "rgba(108,92,231,0.35)" },
  "Other":          { bg: "#636e72", glow: "rgba(99,110,114,0.35)" },
};

const tc = (type) => TYPE_PALETTE[type] || TYPE_PALETTE["Other"];

/* ──────────────────────────────────────────────────────────────────────
   SAMPLE FALLBACK DATA  (shown while figures.json loads or on error)
────────────────────────────────────────────────────────────────────── */
const DEMO_FIGURES = Array.from({ length: 24 }, (_, i) => {
  const types   = Object.keys(TYPE_PALETTE);
  const events  = EVENT_ORDER;
  const makers  = ["Good Smile Company", "Taito", "Max Factory", "Kotobukiya", "Alter", "FuRyu", "SEGA"];
  const year    = 2007 + Math.floor(Math.random() * 18);
  const month   = String(Math.floor(Math.random() * 12) + 1).padStart(2, "0");
  const type    = types[i % types.length];
  const event   = Math.random() > 0.4 ? [events[Math.floor(Math.random() * events.length)]] : [];
  const maker   = makers[i % makers.length];
  return {
    id:           `demo-${i}`,
    name:         `Hatsune Miku ${event[0] || ""} ${year} Ver.`.trim(),
    manufacturer: maker,
    release_date: `${year}-${month}`,
    year,
    type,
    scale:        type === "Scale" ? `1/${[4,6,7,8][i%4]}` : null,
    price_jpy:    type === "Prize" ? null : [5500,6380,12980,16500,19800,24200][i%6],
    image_url:    null,
    events:       event,
    illustrator:  Math.random() > 0.6 ? ILLUSTRATOR_ORDER[i % ILLUSTRATOR_ORDER.length] : null,
    tags:         [type, ...event, maker],
  };
});

/* ──────────────────────────────────────────────────────────────────────
   HELPERS
────────────────────────────────────────────────────────────────────── */

function fmtJPY(n) {
  if (!n) return null;
  return new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" }).format(n);
}

function sortFigures(list, mode) {
  return [...list].sort((a, b) => {
    switch (mode) {
      case "date-desc":  return (b.release_date || "0").localeCompare(a.release_date || "0");
      case "date-asc":   return (a.release_date || "9").localeCompare(b.release_date || "9");
      case "name-asc":   return a.name.localeCompare(b.name);
      case "name-desc":  return b.name.localeCompare(a.name);
      case "maker-asc":  return (a.manufacturer || "").localeCompare(b.manufacturer || "");
      case "price-desc": return (b.price_jpy || 0) - (a.price_jpy || 0);
      case "price-asc":  return (a.price_jpy || Infinity) - (b.price_jpy || Infinity);
      default: return 0;
    }
  });
}

/* ──────────────────────────────────────────────────────────────────────
   SUB-COMPONENTS
────────────────────────────────────────────────────────────────────── */

function TypeBadge({ type, small }) {
  const { bg, glow } = tc(type);
  return (
    <span style={{
      display: "inline-block",
      background: `${bg}18`,
      border: `1px solid ${bg}55`,
      color: bg,
      fontSize: small ? "9px" : "10px",
      fontWeight: 700,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      padding: small ? "2px 6px" : "3px 9px",
      borderRadius: "4px",
      whiteSpace: "nowrap",
    }}>
      {type}
    </span>
  );
}

function Thumbnail({ src, name, type }) {
  const [err, setErr] = useState(false);
  const { bg } = tc(type);
  if (!src || err) {
    return (
      <div style={{
        width: "100%", height: "100%",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        gap: 6, color: "rgba(255,255,255,0.12)",
        background: `radial-gradient(circle at 60% 40%, ${bg}08, transparent 70%)`,
      }}>
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <circle cx="8.5" cy="8.5" r="1.5"/>
          <polyline points="21 15 16 10 5 21"/>
        </svg>
        <span style={{ fontSize: 9, letterSpacing: "0.05em" }}>MFC</span>
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={name}
      loading="lazy"
      onError={() => setErr(true)}
      style={{ width: "100%", height: "100%", objectFit: "cover" }}
    />
  );
}

function FigureCard({ fig, onClick }) {
  const { bg, glow } = tc(fig.type);
  return (
    <article
      onClick={() => onClick(fig)}
      style={{
        background: "rgba(255,255,255,0.025)",
        border: "1px solid rgba(255,255,255,0.06)",
        borderRadius: 14,
        overflow: "hidden",
        cursor: "pointer",
        transition: "transform 0.2s, box-shadow 0.2s, border-color 0.2s",
        animation: "fadeUp 0.35s ease both",
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = "translateY(-4px)";
        e.currentTarget.style.boxShadow = `0 12px 40px ${glow}`;
        e.currentTarget.style.borderColor = `${bg}40`;
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = "";
        e.currentTarget.style.boxShadow = "";
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)";
      }}
    >
      {/* Image */}
      <div style={{ position: "relative", aspectRatio: "3/4", background: "#0a0e18", overflow: "hidden" }}>
        <Thumbnail src={fig.image_url} name={fig.name} type={fig.type} />
        {/* Type overlay */}
        <div style={{
          position: "absolute", top: 8, left: 8,
        }}>
          <TypeBadge type={fig.type} small />
        </div>
        {/* Year chip */}
        <div style={{
          position: "absolute", top: 8, right: 8,
          background: "rgba(0,0,0,0.7)",
          backdropFilter: "blur(6px)",
          border: `1px solid ${bg}40`,
          color: bg,
          fontSize: 10, fontWeight: 800,
          padding: "2px 7px", borderRadius: 4,
        }}>
          {fig.year || "—"}
        </div>
        {/* Event ribbon */}
        {fig.events?.length > 0 && (
          <div style={{
            position: "absolute", bottom: 0, left: 0, right: 0,
            background: "linear-gradient(transparent, rgba(0,0,0,0.85))",
            padding: "20px 8px 8px",
            display: "flex", flexWrap: "wrap", gap: 3,
          }}>
            {fig.events.slice(0, 2).map(ev => (
              <span key={ev} style={{
                fontSize: 9, padding: "1px 5px", borderRadius: 3,
                background: "rgba(255,255,255,0.12)",
                color: "rgba(255,255,255,0.85)",
                letterSpacing: "0.04em",
              }}>{ev}</span>
            ))}
          </div>
        )}
      </div>

      {/* Body */}
      <div style={{ padding: "10px 12px 12px" }}>
        <div style={{
          fontSize: 12, fontWeight: 600, lineHeight: 1.4,
          marginBottom: 4, color: "#e8f4f8",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}>
          {fig.name}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 10, color: "rgba(255,255,255,0.4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "55%" }}>
            {fig.manufacturer || "—"}
          </span>
          <span style={{ fontSize: 11, color: bg, fontWeight: 700 }}>
            {fig.scale || (fig.price_jpy ? fmtJPY(fig.price_jpy) : "")}
          </span>
        </div>
      </div>
    </article>
  );
}

function FigureRow({ fig, onClick }) {
  const { bg } = tc(fig.type);
  return (
    <div
      onClick={() => onClick(fig)}
      style={{
        display: "flex", alignItems: "center", gap: 12,
        background: "rgba(255,255,255,0.02)",
        border: "1px solid rgba(255,255,255,0.05)",
        borderRadius: 10, padding: "10px 16px",
        cursor: "pointer",
        transition: "background 0.15s, border-color 0.15s",
        animation: "fadeUp 0.2s ease both",
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = "rgba(255,255,255,0.04)";
        e.currentTarget.style.borderColor = `${bg}30`;
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = "rgba(255,255,255,0.02)";
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.05)";
      }}
    >
      <div style={{ width: 40, height: 52, borderRadius: 6, overflow: "hidden", flexShrink: 0, background: "#0a0e18" }}>
        <Thumbnail src={fig.image_url} name={fig.name} type={fig.type} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#e8f4f8", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {fig.name}
        </div>
        <div style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", marginTop: 2 }}>
          {fig.manufacturer}{fig.illustrator ? ` · ${fig.illustrator}` : ""}
        </div>
      </div>
      <TypeBadge type={fig.type} small />
      <div style={{ width: 56, textAlign: "center", fontSize: 13, fontWeight: 800, color: bg }}>
        {fig.year || "—"}
      </div>
      <div style={{ width: 50, fontSize: 12, color: "rgba(255,255,255,0.4)", textAlign: "right" }}>
        {fig.scale || ""}
      </div>
      <div style={{ width: 80, fontSize: 11, color: "rgba(255,255,255,0.3)", textAlign: "right" }}>
        {fig.price_jpy ? fmtJPY(fig.price_jpy) : "—"}
      </div>
    </div>
  );
}

function DetailModal({ fig, onClose }) {
  const { bg, glow } = tc(fig.type);
  useEffect(() => {
    const handler = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,0.8)", backdropFilter: "blur(8px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "#0d1322",
          border: `1px solid ${bg}40`,
          borderRadius: 18,
          boxShadow: `0 0 80px ${glow}`,
          maxWidth: 680, width: "100%",
          maxHeight: "90vh", overflow: "auto",
          display: "flex", flexDirection: "column",
        }}
      >
        {/* Header image */}
        <div style={{ position: "relative", height: 240, background: "#060a12", flexShrink: 0 }}>
          <Thumbnail src={fig.image_url} name={fig.name} type={fig.type} />
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(transparent 40%, #0d1322)" }} />
          <button
            onClick={onClose}
            style={{
              position: "absolute", top: 12, right: 12,
              background: "rgba(0,0,0,0.6)", border: "1px solid rgba(255,255,255,0.15)",
              color: "white", borderRadius: 8, padding: "5px 10px", cursor: "pointer",
              fontSize: 12,
            }}
          >✕ Close</button>
          <div style={{ position: "absolute", bottom: 12, left: 20 }}>
            <TypeBadge type={fig.type} />
          </div>
        </div>

        {/* Content */}
        <div style={{ padding: "20px 24px 28px" }}>
          <h2 style={{
            fontSize: 20, fontWeight: 800,
            color: "#e8f4f8", lineHeight: 1.3, marginBottom: 8,
          }}>
            {fig.name}
          </h2>

          {/* Key specs */}
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px,1fr))",
            gap: 10, margin: "16px 0",
          }}>
            {[
              { label: "Manufacturer", value: fig.manufacturer },
              { label: "Release Date", value: fig.release_date },
              { label: "Type", value: fig.type },
              { label: "Scale", value: fig.scale },
              { label: "MSRP", value: fig.price_jpy ? fmtJPY(fig.price_jpy) : null },
              { label: "Illustrator", value: fig.illustrator },
              { label: "Dimensions", value: fig.dimensions },
              { label: "Material", value: fig.material },
              { label: "JAN Code", value: fig.barcode },
              { label: "Owners on MFC", value: fig.mfc_owned_count?.toLocaleString() },
            ].filter(s => s.value).map(spec => (
              <div key={spec.label} style={{
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.07)",
                borderRadius: 8, padding: "8px 12px",
              }}>
                <div style={{ fontSize: 9, color: "rgba(255,255,255,0.3)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 2 }}>
                  {spec.label}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: bg }}>
                  {spec.value}
                </div>
              </div>
            ))}
          </div>

          {/* Events / series */}
          {fig.events?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>Series / Event</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {fig.events.map(ev => (
                  <span key={ev} style={{ fontSize: 12, padding: "3px 10px", borderRadius: 12, background: `${bg}18`, border: `1px solid ${bg}55`, color: bg }}>
                    {ev}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Tags */}
          {fig.tags?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>Tags</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {fig.tags.map(t => (
                  <span key={t} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.5)" }}>
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Description */}
          {fig.description && (
            <p style={{ fontSize: 12, color: "rgba(255,255,255,0.45)", lineHeight: 1.7, marginTop: 14 }}>
              {fig.description}
            </p>
          )}

          {/* MFC link */}
          {fig.detail_url && (
            <a
              href={fig.detail_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: "inline-block", marginTop: 16,
                fontSize: 12, color: bg,
                border: `1px solid ${bg}40`,
                borderRadius: 7, padding: "6px 16px",
                textDecoration: "none",
                transition: "background 0.15s",
              }}
            >
              View on MyFigureCollection ↗
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────
   SIDEBAR FILTER SECTION
────────────────────────────────────────────────────────────────────── */

function FilterSection({ title, children }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ marginBottom: 24 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center",
          background: "none", border: "none", color: "rgba(255,255,255,0.3)",
          fontSize: 10, letterSpacing: "0.18em", textTransform: "uppercase",
          fontFamily: "inherit", cursor: "pointer", padding: "0 20px 8px", fontWeight: 700,
        }}
      >
        {title}
        <span style={{ fontSize: 12, color: "rgba(255,255,255,0.2)" }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && children}
    </div>
  );
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
  const [search, setSearch]         = useState("");
  const [typeFilter, setTypeFilter] = useState("All");
  const [eventFilters, setEventFilters]       = useState([]);
  const [illustratorFilters, setIllFilters]   = useState([]);
  const [makerFilter, setMakerFilter]         = useState("All");
  const [yearFrom, setYearFrom]     = useState(2007);
  const [yearTo, setYearTo]         = useState(new Date().getFullYear());
  const [priceMax, setPriceMax]     = useState("");
  const [sortBy, setSortBy]         = useState("date-desc");
  const [viewMode, setViewMode]     = useState("grid");
  const [selected, setSelected]     = useState(null);

  /* ── Load data ── */
  useEffect(() => {
    async function load() {
      try {
        const [figRes, metaRes] = await Promise.all([
          fetch(FIGURES_JSON_URL),
          fetch(META_JSON_URL).catch(() => null),
        ]);
        if (!figRes.ok) throw new Error("figures.json not found");
        const figs = await figRes.json();
        setFigures(figs);
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

  /* ── Derived data for filter options ── */
  const allMakers = useMemo(() => {
    const s = new Set(figures.map(f => f.manufacturer).filter(Boolean));
    return ["All", ...Array.from(s).sort()];
  }, [figures]);

  const typeCounts = useMemo(() => {
    const m = {};
    figures.forEach(f => { m[f.type] = (m[f.type] || 0) + 1; });
    return m;
  }, [figures]);

  const eventCounts = useMemo(() => {
    const m = {};
    figures.forEach(f => f.events?.forEach(ev => { m[ev] = (m[ev] || 0) + 1; }));
    return m;
  }, [figures]);

  const illCounts = useMemo(() => {
    const m = {};
    figures.forEach(f => { if (f.illustrator) m[f.illustrator] = (m[f.illustrator] || 0) + 1; });
    return m;
  }, [figures]);

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
    list = list.filter(f => {
      const y = f.year || 0;
      return y >= yearFrom && y <= yearTo;
    });
    if (priceMax !== "") {
      const max = parseInt(priceMax);
      list = list.filter(f => !f.price_jpy || f.price_jpy <= max);
    }
    return sortFigures(list, sortBy);
  }, [figures, search, typeFilter, makerFilter, eventFilters, illustratorFilters, yearFrom, yearTo, priceMax, sortBy]);

  const toggleEvent = useCallback(ev => setEventFilters(p => p.includes(ev) ? p.filter(x => x !== ev) : [...p, ev]), []);
  const toggleIll   = useCallback(il => setIllFilters(p => p.includes(il) ? p.filter(x => x !== il) : [...p, il]), []);

  const clearAll = useCallback(() => {
    setSearch(""); setTypeFilter("All"); setEventFilters([]); setIllFilters([]);
    setMakerFilter("All"); setYearFrom(2007); setYearTo(new Date().getFullYear()); setPriceMax("");
  }, []);

  const hasFilters = search || typeFilter !== "All" || eventFilters.length || illustratorFilters.length ||
    makerFilter !== "All" || yearFrom > 2007 || yearTo < new Date().getFullYear() || priceMax !== "";

  /* ── CSS ── */
  const css = `
    @import url('https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;700;900&family=Syne:wght@400;600;700;800&display=swap');
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #06090f;
      --bg2: #0a0e18;
      --bg3: #0e1424;
      --border: rgba(255,255,255,0.07);
      --text: #ddeeff;
      --muted: rgba(221,238,255,0.35);
      --teal: #39c5bb;
      --pink: #ff79c6;
    }
    html, body { background: var(--bg); color: var(--text); font-family: 'Syne', sans-serif; line-height: 1.5; }
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(8px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes shimmer {
      0%,100% { opacity: 0.4; } 50% { opacity: 0.8; }
    }
    * { transition: background-color 0.15s; }
  `;

  /* ── LOADING STATE ── */
  if (loading) return (
    <>
      <style>{css}</style>
      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 20,
        background: "var(--bg)",
      }}>
        <div style={{
          width: 64, height: 64, borderRadius: "50%",
          border: "2px solid rgba(255,255,255,0.05)",
          borderTop: "2px solid #39c5bb",
          borderRight: "2px solid #ff79c6",
          animation: "spin 0.7s linear infinite",
        }} />
        <style>{"@keyframes spin { to { transform: rotate(360deg); } }"}</style>
        <div style={{ color: "var(--muted)", fontSize: 14 }}>Loading figure archive…</div>
      </div>
    </>
  );

  /* ── MAIN RENDER ── */
  return (
    <>
      <style>{css}</style>

      {/* ── HEADER ── */}
      <header style={{
        position: "relative",
        background: "linear-gradient(160deg, #08101e 0%, #060910 60%, #0a0614 100%)",
        borderBottom: "1px solid var(--border)",
        overflow: "hidden",
        padding: "32px 28px 24px",
      }}>
        {/* Background glow orbs */}
        <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
          <div style={{ position: "absolute", top: "-40%", left: "30%", width: 500, height: 300, background: "radial-gradient(ellipse, rgba(57,197,187,0.1) 0%, transparent 70%)", filter: "blur(20px)" }} />
          <div style={{ position: "absolute", top: "-20%", right: "10%", width: 300, height: 200, background: "radial-gradient(ellipse, rgba(255,121,198,0.07) 0%, transparent 70%)", filter: "blur(20px)" }} />
          {/* Subtle grid */}
          <div style={{ position: "absolute", inset: 0, backgroundImage: "linear-gradient(rgba(255,255,255,0.015) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.015) 1px, transparent 1px)", backgroundSize: "40px 40px" }} />
        </div>

        <div style={{ position: "relative", maxWidth: 1440, margin: "0 auto" }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap", justifyContent: "space-between" }}>
            <div>
              <div style={{ fontSize: 11, letterSpacing: "0.3em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 6, fontFamily: "'Zen Kaku Gothic New', sans-serif" }}>
                初音ミク · Hatsune Miku
              </div>
              <h1 style={{
                fontSize: "clamp(26px, 5vw, 54px)",
                fontWeight: 800,
                letterSpacing: "-0.03em",
                lineHeight: 1.05,
                background: "linear-gradient(135deg, #39c5bb 0%, #a3e8e4 30%, #ff79c6 80%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
              }}>
                Figure Archive
              </h1>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
                The complete catalog · scraped daily from MyFigureCollection.net
              </div>
            </div>

            {/* Stats */}
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {[
                { label: "Total Figures", value: figures.length.toLocaleString() },
                { label: "Shown", value: filtered.length.toLocaleString() },
                { label: "Last Updated", value: meta?.last_updated ? new Date(meta.last_updated).toLocaleDateString("en-SG") : "Demo" },
              ].map(s => (
                <div key={s.label} style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: 10, padding: "8px 16px", textAlign: "center",
                }}>
                  <div style={{ fontSize: 10, color: "var(--muted)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{s.label}</div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: "#39c5bb", lineHeight: 1.2 }}>{s.value}</div>
                </div>
              ))}
            </div>
          </div>

          {usingDemo && (
            <div style={{
              marginTop: 14,
              background: "rgba(255,159,67,0.1)", border: "1px solid rgba(255,159,67,0.3)",
              borderRadius: 8, padding: "8px 14px",
              fontSize: 12, color: "#ffb86c",
              display: "inline-block",
            }}>
              ⚠ Demo mode — <code style={{ fontFamily: "monospace" }}>figures.json</code> not found. Run the scraper to populate real data.
            </div>
          )}
        </div>
      </header>

      {/* ── BODY ── */}
      <div style={{ display: "flex", maxWidth: 1440, margin: "0 auto", width: "100%" }}>

        {/* ── SIDEBAR ── */}
        <aside style={{
          width: 270, flexShrink: 0,
          borderRight: "1px solid var(--border)",
          padding: "24px 0",
          position: "sticky", top: 0, height: "100vh", overflowY: "auto",
        }}>

          {/* Clear filters */}
          {hasFilters && (
            <div style={{ padding: "0 20px", marginBottom: 18 }}>
              <button onClick={clearAll} style={{
                width: "100%", background: "rgba(255,79,79,0.1)", border: "1px solid rgba(255,79,79,0.3)",
                color: "#ff7979", borderRadius: 8, padding: "7px", cursor: "pointer",
                fontSize: 12, fontFamily: "inherit", fontWeight: 600,
              }}>
                ✕ Clear all filters
              </button>
            </div>
          )}

          {/* Figure Type */}
          <FilterSection title="Figure Type">
            <div style={{ padding: "0 12px", display: "flex", flexDirection: "column", gap: 2 }}>
              {["All", ...TYPE_ORDER].map(t => {
                const count = t === "All" ? figures.length : (typeCounts[t] || 0);
                const { bg } = tc(t);
                const active = typeFilter === t;
                return count > 0 || t === "All" ? (
                  <button key={t} onClick={() => setTypeFilter(t)} style={{
                    display: "flex", alignItems: "center", gap: 8,
                    background: active ? `${bg}12` : "transparent",
                    border: `1px solid ${active ? `${bg}40` : "transparent"}`,
                    borderRadius: 8, padding: "7px 10px", cursor: "pointer",
                    fontFamily: "inherit", color: active ? bg : "var(--muted)",
                    fontSize: 13, fontWeight: active ? 700 : 400,
                    textAlign: "left",
                    transition: "all 0.15s",
                  }}>
                    {t !== "All" && <span style={{ width: 7, height: 7, borderRadius: "50%", background: bg, flexShrink: 0 }} />}
                    <span style={{ flex: 1 }}>{t}</span>
                    <span style={{ fontSize: 10, color: "rgba(255,255,255,0.2)" }}>{count}</span>
                  </button>
                ) : null;
              })}
            </div>
          </FilterSection>

          {/* Events / Series */}
          <FilterSection title="Series / Event">
            <div style={{ padding: "0 20px", display: "flex", flexWrap: "wrap", gap: 5 }}>
              {EVENT_ORDER.filter(ev => eventCounts[ev]).map(ev => {
                const on = eventFilters.includes(ev);
                return (
                  <button key={ev} onClick={() => toggleEvent(ev)} style={{
                    fontSize: 11, padding: "3px 9px", borderRadius: 12,
                    border: `1px solid ${on ? "#39c5bb88" : "rgba(255,255,255,0.1)"}`,
                    background: on ? "rgba(57,197,187,0.12)" : "rgba(255,255,255,0.03)",
                    color: on ? "#39c5bb" : "var(--muted)",
                    cursor: "pointer", fontFamily: "inherit",
                    transition: "all 0.15s",
                  }}>
                    {ev}
                    <span style={{ fontSize: 9, color: "rgba(255,255,255,0.2)", marginLeft: 4 }}>{eventCounts[ev]}</span>
                  </button>
                );
              })}
            </div>
          </FilterSection>

          {/* Illustrator */}
          <FilterSection title="Illustrator / Artist">
            <div style={{ padding: "0 20px", display: "flex", flexWrap: "wrap", gap: 5 }}>
              {ILLUSTRATOR_ORDER.filter(il => illCounts[il]).map(il => {
                const on = illustratorFilters.includes(il);
                return (
                  <button key={il} onClick={() => toggleIll(il)} style={{
                    fontSize: 11, padding: "3px 9px", borderRadius: 12,
                    border: `1px solid ${on ? "#ff79c688" : "rgba(255,255,255,0.1)"}`,
                    background: on ? "rgba(255,121,198,0.1)" : "rgba(255,255,255,0.03)",
                    color: on ? "#ff79c6" : "var(--muted)",
                    cursor: "pointer", fontFamily: "inherit",
                    transition: "all 0.15s",
                  }}>
                    {il}
                    <span style={{ fontSize: 9, color: "rgba(255,255,255,0.2)", marginLeft: 4 }}>{illCounts[il]}</span>
                  </button>
                );
              })}
            </div>
          </FilterSection>

          {/* Manufacturer */}
          <FilterSection title="Manufacturer">
            <div style={{ padding: "0 20px" }}>
              <select value={makerFilter} onChange={e => setMakerFilter(e.target.value)} style={{
                width: "100%", background: "#0e1424",
                border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8,
                color: "var(--text)", padding: "8px 10px", fontSize: 12,
                fontFamily: "inherit", outline: "none", cursor: "pointer",
              }}>
                {allMakers.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          </FilterSection>

          {/* Year Range */}
          <FilterSection title="Release Year">
            <div style={{ padding: "0 20px", display: "flex", gap: 8 }}>
              <input type="number" value={yearFrom} min={2007} max={yearTo}
                onChange={e => setYearFrom(+e.target.value)}
                style={{ flex: 1, background: "#0e1424", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 7, color: "var(--text)", padding: "7px 8px", fontSize: 12, fontFamily: "inherit", textAlign: "center", outline: "none" }} />
              <span style={{ color: "var(--muted)", alignSelf: "center" }}>–</span>
              <input type="number" value={yearTo} min={yearFrom} max={2030}
                onChange={e => setYearTo(+e.target.value)}
                style={{ flex: 1, background: "#0e1424", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 7, color: "var(--text)", padding: "7px 8px", fontSize: 12, fontFamily: "inherit", textAlign: "center", outline: "none" }} />
            </div>
          </FilterSection>

          {/* Max Price */}
          <FilterSection title="Max Price (JPY)">
            <div style={{ padding: "0 20px" }}>
              <input
                type="number" placeholder="e.g. 15000" value={priceMax}
                onChange={e => setPriceMax(e.target.value)}
                style={{
                  width: "100%", background: "#0e1424",
                  border: "1px solid rgba(255,255,255,0.1)", borderRadius: 7,
                  color: "var(--text)", padding: "7px 10px", fontSize: 12,
                  fontFamily: "inherit", outline: "none",
                }}
              />
            </div>
          </FilterSection>

          {/* Type breakdown chart (mini) */}
          {meta?.by_type && (
            <FilterSection title="Collection Breakdown">
              <div style={{ padding: "0 20px", display: "flex", flexDirection: "column", gap: 5 }}>
                {Object.entries(meta.by_type).slice(0, 7).map(([type, count]) => {
                  const pct = Math.round((count / figures.length) * 100);
                  const { bg } = tc(type);
                  return (
                    <div key={type}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--muted)", marginBottom: 3 }}>
                        <span>{type}</span><span>{count}</span>
                      </div>
                      <div style={{ height: 3, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${pct}%`, background: bg, borderRadius: 2 }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </FilterSection>
          )}
        </aside>

        {/* ── MAIN CONTENT ── */}
        <main style={{ flex: 1, padding: "24px 24px 40px", minWidth: 0 }}>

          {/* Toolbar */}
          <div style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap", alignItems: "center" }}>
            {/* Search */}
            <div style={{ flex: 1, minWidth: 200, position: "relative" }}>
              <svg style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", opacity: 0.3 }}
                width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input
                placeholder="Search figures, makers, tags…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{
                  width: "100%", background: "var(--bg3)",
                  border: "1px solid var(--border)", borderRadius: 10,
                  color: "var(--text)", padding: "10px 12px 10px 32px",
                  fontSize: 13, fontFamily: "inherit", outline: "none",
                }}
              />
            </div>

            {/* Sort */}
            <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{
              background: "var(--bg3)", border: "1px solid var(--border)",
              borderRadius: 10, color: "var(--text)", padding: "10px 12px",
              fontSize: 13, fontFamily: "inherit", outline: "none", cursor: "pointer",
            }}>
              {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>

            {/* View toggle */}
            <div style={{ display: "flex", border: "1px solid var(--border)", borderRadius: 9, overflow: "hidden" }}>
              {[["grid", "⊞"], ["list", "≡"]].map(([mode, icon]) => (
                <button key={mode} onClick={() => setViewMode(mode)} style={{
                  padding: "9px 13px", background: viewMode === mode ? "rgba(57,197,187,0.12)" : "transparent",
                  border: "none", color: viewMode === mode ? "#39c5bb" : "var(--muted)",
                  cursor: "pointer", fontSize: 17, transition: "all 0.15s",
                }}>
                  {icon}
                </button>
              ))}
            </div>
          </div>

          {/* Results info + active filters */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>
              <strong style={{ color: "#39c5bb" }}>{filtered.length}</strong> of {figures.length} figures
            </span>
            {[...eventFilters, ...illustratorFilters].map(tag => (
              <span key={tag} onClick={() => { toggleEvent(tag); toggleIll(tag); }} style={{
                fontSize: 10, padding: "2px 8px", borderRadius: 10,
                background: "rgba(57,197,187,0.1)", border: "1px solid rgba(57,197,187,0.3)",
                color: "#39c5bb", cursor: "pointer",
              }}>
                {tag} ✕
              </span>
            ))}
          </div>

          {/* Figure list */}
          {filtered.length === 0 ? (
            <div style={{ textAlign: "center", padding: "80px 20px", color: "var(--muted)" }}>
              <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.4 }}>🎌</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text)", marginBottom: 6 }}>No figures found</div>
              <div style={{ fontSize: 13 }}>Try adjusting your filters</div>
            </div>
          ) : viewMode === "grid" ? (
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(175px, 1fr))",
              gap: 14,
            }}>
              {filtered.map((fig, i) => (
                <div key={fig.id} style={{ animationDelay: `${Math.min(i, 32) * 22}ms` }}>
                  <FigureCard fig={fig} onClick={setSelected} />
                </div>
              ))}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              {filtered.map((fig, i) => (
                <div key={fig.id} style={{ animationDelay: `${Math.min(i, 24) * 15}ms` }}>
                  <FigureRow fig={fig} onClick={setSelected} />
                </div>
              ))}
            </div>
          )}
        </main>
      </div>

      {/* ── DETAIL MODAL ── */}
      {selected && <DetailModal fig={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
