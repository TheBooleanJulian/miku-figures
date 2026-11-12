#!/usr/bin/env python3
"""
HLJ Scraper — Hatsune Miku Figure Archive
==========================================
Scrapes HobbyLink Japan (hlj.com) for Hatsune Miku figures. Replaces the MFC
scraper, which MyFigureCollection blocks (403 / security check) from automated
clients. Standard library only.

Usage:
    python hlj_scraper.py                  # full scrape -> figures.json
    python hlj_scraper.py --incremental    # only fetch figures not already saved
    python hlj_scraper.py --limit 2        # first 2 listing pages (dev/test)

Output:
    ../public/figures.json
    ../public/meta.json

Prices: `price_jpy` comes from the page's JSON-LD; `price_sgd` is what HLJ
displays when the currency cookie is set to SGD (the site UI shows SGD).
"""

import argparse
import html
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

HLJ_BASE = "https://www.hlj.com"
# "miku" (not "hatsune miku") also catches Snow Miku / Racing Miku titles; figma
# action figures sit outside HLJ's "Figures" category, so they get their own query.
LIST_QUERIES = [
    "Word=miku&GenreCode2=Figures",
    "Word=figma+miku",
]
LIST_URL = HLJ_BASE + "/search/?{query}&Page={page}"
MAX_PAGES = 80                  # hard cap per query; "miku" listing has ~57 pages
OUTPUT_DIR = Path(__file__).parent.parent / "public"
FIGURES_FILE = OUTPUT_DIR / "figures.json"
META_FILE = OUTPUT_DIR / "meta.json"
DELAY_BETWEEN_PAGES = 1.5       # seconds — be polite
DELAY_BETWEEN_ITEMS = 0.8
FIGURE_CATEGORIES = ("Figures", "Action Figures")
MAX_CONSECUTIVE_FAILURES = 8    # stop instead of hammering a site that blocks us

# HLJ picks the display currency from this cookie (default is GeoIP-based).
CURRENCY_COOKIE = "hljCurrencyData=" + urllib.parse.quote(json.dumps({
    "currencyCode": "SGD", "currencyName": "Singapore Dollar",
    "currencyPrecision": 2, "currencyPattern": "$%s", "currencySymbol": "$",
    "selectedManually": 1,
}, separators=(",", ":")))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": CURRENCY_COOKIE,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("hlj-scraper")

# ──────────────────────────────────────────────
# TYPE / EVENT NORMALISATION
# ──────────────────────────────────────────────

TYPE_MAP = {
    "nendoroid":     "Nendoroid",
    "figma":         "Figma",
    "pop up parade": "Pop Up Parade",
    "prize":         "Prize",
    "plush":         "Plush / Soft",
    "petit":         "Mini / Petite",
    "mini":          "Mini / Petite",
    "trading":       "Mini / Petite",
    "chibi":         "Mini / Petite",
    "bust":          "Bust",
    "garage kit":    "Garage Kit",
    "statue":        "Other",
}

# Series, events, songs and collaborations, matched as substrings of the
# lower-cased name. The site builds its filter chips from whatever appears here.
EVENT_KEYWORDS = {
    "Snow Miku":            ["snow miku", "snow ver", "yuki miku"],
    "Racing Miku":          ["racing miku", "hatsune miku gt", "racing ver"],
    "Sakura Miku":          ["sakura miku"],
    "Magical Mirai":        ["magical mirai", "magic mirai"],
    "Miku Expo":            ["expo"],
    "Symphony":             ["symphony"],
    "Miku with You":        ["miku with you"],
    "Project DIVA":         ["project diva"],
    "Project SEKAI":        ["project sekai", "colorful stage"],
    "Digital Stars":        ["digital stars"],
    "39Culture":            ["39culture", "39 culture"],
    "Anniversary / Birthday": ["anniversary", "birthday"],
    "Append":               ["append"],
    "Live Stage":           ["live stage", "live concert"],
    "Dreamy Vocal":         ["dreamy vocal"],
    "Halloween":            ["halloween", "trick or miku", "trick or treat"],
    "Christmas":            ["christmas", "xmas"],
    "New Year":             ["new year"],
    "Hokusai":              ["hokusai"],
    "Cinnamoroll":          ["cinnamoroll"],
    "Sanrio":               ["kuromi", "my melody", "hello kitty", "pompompurin", "pochacco", "sanrio"],
    "Rascal":               ["rascal"],
    "Rody":                 ["rody"],
    "Gundam":               ["gundam"],
    "World is Mine":        ["world is mine", "worldismine"],
    "Senbonzakura":         ["senbonzakura"],
    "Tell Your World":      ["tell your world"],
    "Deep Sea Girl":        ["deep sea girl", "kaizokunyan"],
    "Rabbit Hole":          ["rabbit hole"],
    "Vampire":              ["vampire"],
    "Love is War":          ["love is war"],
    "Sand Planet":          ["sand planet"],
    "BEAST RINGER":         ["beast ringer"],
    "Mikudayo":             ["mikudayo"],
}

# Illustrators / artists credited in product names ("Art by X", "X Ver.",
# "feat. X", "Hatsune Miku x X"). Regexes on the lower-cased name, word-bounded
# so short names (KEI, neco, Lack) don't match inside other words.
ILLUSTRATORS = {
    "KEI":              r"\bkei\b",
    "Rella":            r"\brella\b",
    "iXima":            r"\bixima\b",
    "Fuzichoco":        r"\bfuzichoco\b",
    "Saine":            r"\bsaine\b",
    "GEMI":             r"\bgemi\b",
    "Ontama":           r"\bontama\b",
    "Yunomachi":        r"\byunomachi\b",
    "raemz":            r"\braemz\b",
    "azurite":          r"\bazurite\b",
    "Mikatan":          r"\bmikatan\b",
    "Mai Yoneyama":     r"\byoneyama\b",
    "Maho Takahashi":   r"maho takahashi|takahashi maho",
    "Natsuki Amashiro": r"\bamashiro\b",
    "Rosuuri":          r"\brosuuri\b",
    "rurudo":           r"\brurudo\b",
    "SanMuYYB":         r"\bsanmuyyb\b",
    "neco":             r"by neco\b",
    "Lack":             r"by lack\b",
    "Hidari":           r"\bhidari\b",
    "Tony Taka":        r"\btony\b",
    "Rassu":            r"\brassu\b",
    "Coalowl":          r"\bcoalowl\b",
    "Suou":             r"\bsuou\b",
    "Omutatsu":         r"\bomutatsu\b",
    "Kentaro Yabuki":   r"\byabuki\b",
    "Nekozakana":       r"\bnekozakana\b",
    "Annindoufu":       r"\bannindoufu\b",
    "Mika Pikazo":      r"\bmika pikazo\b",
}
ILLUSTRATOR_RES = {name: re.compile(p) for name, p in ILLUSTRATORS.items()}

SCALE_RE = re.compile(r"\b1/(\d+)\b")


# Goods that HLJ files under "Figures" but that aren't figures.
MERCH_RE = re.compile(
    r"tapestr|towel|t-shirt|\bt shirt|jersey|key ?chain|\bcase\b|code clip|\bplate\b|"
    r"costume set|\btote\b|sticker|poster|\bmug\b|\bcup\b|\bbags?\b|backpack|hoodie|sweatshirt|"
    r"parka|acrylic|badge|clear file|blanket|pouch|notebook|cushion|umbrella|wallet|"
    r"smartphone|\bpins?\b|\bsocks?\b|pinback|\bbutton\b|postcard|decorative art|calendar|luggage|mirror|shikishi|ticket|rubber mat|puzzle|card holder|hanging scroll|amulet|otamatone|\[used item|"
    r"pillow|eye mask|massage|shawl|\bscarf\b(?!\))|binder|photo frame|\bcharms?\b",   # "(Scarf)" = a plush variant
    re.I,
)
# "Miku" as a name, not inside Mikuru (Haruhi) or Mikuro (Shiino); Mikudayo,
# DecoMiku and Mikuzukin still count.
MIKU_RE = re.compile(r"miku(?!r[uo])", re.I)
# Another Vocaloid is the actual product (e.g. "... Kurumitapinui MEIKO")
OTHER_CHARACTER_RE = re.compile(
    r"(meiko|kaito|(rin|len) kagamine|kagamine (rin|len)|luka megurine|megurine luka)\)?$", re.I)
# Characters other than Miku who are sold under a Miku franchise label
OTHER_CHAR_RE = re.compile(
    r"\b(?:kagamine|rin|len|megurine|luka|meiko|kaito|gumi|kasane|teto|akita|neru|yowane|haku|"
    r"sonico)\b", re.I)
# Franchise labels that put "Hatsune Miku" in a name without the product being
# Miku: "Hatsune Miku Series: Kagamine Rin ...", "Hatsune Miku -Project DIVA- F 2nd:
# Megurine Luka ...", "Hatsune Miku GT Project: Super Sonico ...", lottery names.
FRANCHISE_LABEL_RE = re.compile(
    r"(?:hatsune miku|miku hatsune)\s+series\b|"
    r"(?:hatsune miku|miku hatsune)\s*-?\s*project diva\s*-?(?:\s*(?:f\s*2nd|f|x|arcade|future tone|"
    r"mega\s*39'?s|2nd|extend|dreamy theater))*|"
    r"(?:hatsune miku|miku hatsune)\s+gt project|"
    r"(?:happy\s*kuji\s*)+(?:hatsune miku|miku hatsune)|"
    r"piapro characters?|character vocal series\s*0?\d", re.I)
# A name that merely starts with "Hatsune Miku" ("Hatsune Miku BiCute Bunnies Figure
# Megurine Luka"): only used when another character is named, and Miku must then
# appear again later in the name.
LEADING_LABEL_RE = re.compile(r"^\s*(?:hatsune miku|miku hatsune)\b\s*[-:]?", re.I)
# Project Sekai (PJSK) goods of other characters carry "feat. Hatsune Miku" or
# "Hatsune Miku: Colorful Stage!" as a franchise label. For those, Miku must
# appear once the label is stripped.
PJSK_RE = re.compile(r"project sekai|colorful stage", re.I)
PJSK_LABEL_RE = re.compile(
    r"feat\.?\s*(?:hatsune miku|miku hatsune)|\([^)]*colorful stage[^)]*\)|"
    r"(?:hatsune miku|miku hatsune)\s*:?\s*colorful stage!?|"
    r"the broken world and miku who can'?\s?t sing|miku who can'?\s?t sing", re.I)
# Other characters who happen to be called Miku (Nakano Miku, Miku Maekawa, ...)
NOT_VOCALOID_RE = re.compile(
    r"quintessential|nakano|maekawa|izayoi|miku ogawa|date a live|idolm@?ster|love live|"
    r"mikuru|mikuro|haruhi|shiino", re.I)
HATSUNE_RE = re.compile(r"hatsune|hastune", re.I)
# Name signals that an item is the Vocaloid even if HLJ files it under another series
VOCALOID_NAME_RE = re.compile(
    r"hatsune|hastune|sakura miku|snow miku|yuki miku|racing miku|mikuzukin|miku with you", re.I)
PLUSH_RE = re.compile(r"plush|mascot|nui|kurumi|chibigurumi|fluffy|fuwa|yurayura|swaying", re.I)
PRIZE_RE = re.compile(
    r"amp\+?|noodle stopper|wonderland|exceed creative|trio-try-it|luminasta|espresto|"
    r"sweet sweets|fuwapuchi|figure|^pm|4\.5 chan|look up|artist collaboration",
    re.I,
)
PRIZE_MAKERS = ("taito", "furyu", "sega", "banpresto", "bandai spirits", "bandai namco")


def classify(name: str, maker: str | None) -> str | None:
    """Figure type for a product, or None if it is merchandise / not a Miku figure."""
    if PJSK_RE.search(name) and not MIKU_RE.search(PJSK_LABEL_RE.sub(" ", name)):
        return None
    # Another franchise's "Miku", or a crossover like "Love Live SNOW MIKU 2016 Stuffed
    # Rin Hoshizora": keep only if Hatsune Miku is named, or Miku is named a second
    # time after the crossover label ("... Stuffed SNOW MIKU 2016")
    if NOT_VOCALOID_RE.search(name) and not HATSUNE_RE.search(name) \
            and len(VOCALOID_NAME_RE.findall(name)) < 2:
        return None
    if not MIKU_RE.search(name) or MERCH_RE.search(name) or OTHER_CHARACTER_RE.search(name.strip()):
        return None
    core = FRANCHISE_LABEL_RE.sub(" ", PJSK_LABEL_RE.sub(" ", name))
    core = LEADING_LABEL_RE.sub(" ", core)  # "Hatsune Miku - Kaito Mochipiko Plush"
    if OTHER_CHAR_RE.search(core) and not MIKU_RE.search(core):
        return None                         # Rin/Len/Luka/... sold under a Miku label
    low = name.lower()
    for key, label in TYPE_MAP.items():
        if key in low:
            return label
    if PLUSH_RE.search(name):
        return "Plush / Soft"
    if SCALE_RE.search(name):
        return "Scale"
    if (maker or "").lower().startswith(PRIZE_MAKERS) or PRIZE_RE.search(name):
        return "Prize"
    return "Other"


def extract_events(name: str) -> list[str]:
    low = name.lower()
    return [ev for ev, kws in EVENT_KEYWORDS.items() if any(k in low for k in kws)]


def extract_illustrator(name: str) -> str | None:
    low = name.lower()
    for artist, rx in ILLUSTRATOR_RES.items():
        if rx.search(low):
            return artist
    return None


def retag(f: dict) -> dict:
    """Recompute events, illustrator and tags from the name, so rows saved by an
    older version (or another scraper) pick up keyword-list changes."""
    f["events"] = extract_events(f.get("name", ""))
    f["illustrator"] = extract_illustrator(f.get("name", ""))
    tags = [f.get("type"), *f["events"], f.get("manufacturer"), f.get("series")]
    f["tags"] = list(dict.fromkeys(t for t in tags if t))
    return f


# ──────────────────────────────────────────────
# HTTP
# ──────────────────────────────────────────────

class Blocked(Exception):
    """Too many consecutive failures — probably blocked or site down."""


_failures = 0


def get_html(url: str, retries: int = 2) -> str | None:
    global _failures
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", "replace")
            _failures = 0
            return body
        except urllib.error.HTTPError as e:
            log.warning(f"HTTP {e.code} for {url} (attempt {attempt + 1}/{retries})")
            if e.code in (403, 429):        # don't retry a block
                break
        except Exception as e:
            log.warning(f"{type(e).__name__} for {url} (attempt {attempt + 1}/{retries}): {e}")
        time.sleep(3 * (attempt + 1))
    _failures += 1
    if _failures >= MAX_CONSECUTIVE_FAILURES:
        raise Blocked(f"{_failures} consecutive failures, last: {url}")
    return None


# ──────────────────────────────────────────────
# PARSERS
# ──────────────────────────────────────────────

ITEM_RE = re.compile(
    r'<a class="item-img-wrapper" href="(?P<href>/[^"]+)">\s*<img\s+src="(?P<img>[^"]+)"'
    r'.*?<p class="product-item-name[^"]*">\s*<a\s+href="[^"]+">\s*(?P<name>.*?)\s*</a>',
    re.S,
)


def parse_listing(page_html: str) -> list[dict]:
    stubs = []
    for m in ITEM_RE.finditer(page_html):
        href = m.group("href")
        code = href.rsplit("-", 1)[-1].upper()
        stubs.append({
            "id": code,
            "name": html.unescape(re.sub(r"\s+", " ", m.group("name"))).strip(),
            "detail_url": HLJ_BASE + href,
        })
    return stubs


def _li(page_html: str, label: str) -> str | None:
    m = re.search(rf"<li[^>]*>\s*{re.escape(label)}:\s*(.*?)</li>", page_html, re.S)
    if not m:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
    return re.sub(r"\s+", " ", text).strip() or None


# ──────────────────────────────────────────────
# DESCRIPTION CLEANING
# ──────────────────────────────────────────────

SIZE_RE = re.compile(r"\[\s*(?:figure\s+)?size\s*\]\s*:?\s*([^\[]+)", re.I)
# Sentences that are a call to action rather than a description
SALES_RE = re.compile(
    r"\b(?:pre-?)?order\b[^.!?]*\b(?:today|now|yours|soon)\b|don'?t miss|do not miss|"
    r"be sure to|make sure (?:to|you)|add (?:her|him|it|this) to your|bring (?:her|him|it|this) home|"
    r"get (?:yours|your|her|him)|grab (?:yours|her|him|one)|check (?:it|her|him) out|"
    r"won'?t want to miss|in your (?:own )?collection|on display in your|"
    r"to (?:any|every|a) (?:fan'?s )?collection|placing your order|manufacturer'?s defects|"
    r"touch-up work|sizes tend to run|please (?:note|keep this in mind)|"
    r"^(?:bring|add|reserve|secure|snag|pick up|take home|welcome)\b",
    re.I,
)


def clean_description(raw: str | None) -> tuple[str, str | None]:
    """Return (clean description, figure size).

    Decodes HTML entities (twice: the text is often double-escaped), strips tags
    and sales sentences, and moves the "[Figure Size]: ..." note out of the prose.
    """
    text = raw or ""
    for _ in range(2):
        text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    size = None
    m = SIZE_RE.search(text)
    if m:
        size = m.group(1).strip().rstrip(".") or None
        text = (text[:m.start()] + text[m.end():]).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(s for s in sentences if s and not SALES_RE.search(s)).strip(), size


def parse_detail(page_html: str, stub: dict) -> dict | None:
    """Enrich a listing stub with detail-page data. None = not a figure (skip)."""
    ld = {}
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', page_html, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    item_type = _li(page_html, "Item Type") or ""
    category = _li(page_html, "Category") or ""
    series = _li(page_html, "Series")
    if "kit" in item_type.lower():          # model kits (e.g. Nendoroid Plamo) aren't figures
        return None
    if category not in FIGURE_CATEGORIES:   # apparel, fun goods, cosmetics, ...
        return None
    if series and series.lower() != "vocaloid" and not VOCALOID_NAME_RE.search(stub["name"]):
        return None                         # a different franchise's Miku

    name = html.unescape(ld.get("name") or stub["name"]).strip()
    maker = ((ld.get("brand") or {}).get("name")) or _li(page_html, "Manufacturer")
    typ = classify(name, maker)
    if typ is None:
        return None

    release = None
    rd = _li(page_html, "Release Date")
    if rd and (dm := re.match(r"(\d{4})/(\d{2})", rd)):
        release = f"{dm.group(1)}-{dm.group(2)}"

    price_jpy = None
    try:
        price_jpy = int(float(ld["offers"]["price"]))
    except (KeyError, TypeError, ValueError):
        pass

    price_sgd = None
    pm = re.search(r'<p class="price[^"]*">\s*\$?([\d,]+(?:\.\d+)?)\s*SGD', page_html)
    if pm:
        price_sgd = float(pm.group(1).replace(",", ""))

    desc, desc_size = clean_description(ld.get("description"))
    scale_m = SCALE_RE.search(name)

    events = extract_events(name)
    if "stuffed animals" in item_type.lower() and typ not in ("Nendoroid", "Figma"):
        typ = "Plush / Soft"                # HLJ files plush and dolls under this item type

    return {
        "id": stub["id"],
        "name": name,
        "manufacturer": maker,
        "release_date": release,
        "year": int(release[:4]) if release else None,
        "type": typ,
        "scale": f"1/{scale_m.group(1)}" if scale_m else None,
        "price_jpy": price_jpy,
        "price_sgd": price_sgd,
        "image_url": ld.get("image"),
        "detail_url": stub["detail_url"],
        "events": events,
        "illustrator": extract_illustrator(name),
        "tags": [t for t in [typ, *events, maker, series] if t],
        "description": desc,
        "dimensions": desc_size,
        "material": None,
        "barcode": ld.get("gtin13") or _li(page_html, "JAN Code"),
        "mfc_owned_count": None,
        "series": series,
        "category": category,
        "item_type": item_type,
        "source": "hlj",
    }


# ──────────────────────────────────────────────
# STORAGE
# ──────────────────────────────────────────────

def load_existing() -> dict[str, dict]:
    if FIGURES_FILE.exists():
        try:
            data = json.loads(FIGURES_FILE.read_text(encoding="utf-8"))
            # Only keep rows that came from this scraper; drop old sample/MFC rows.
            rows = {}
            for f in data:
                if not f.get("id") or f.get("source") != "hlj":
                    continue
                if "category" not in f:     # saved before HLJ Category filtering: refetch and re-judge
                    continue
                typ = classify(f.get("name", ""), f.get("manufacturer"))
                if typ is None:             # rules changed: drop goods saved earlier
                    continue
                f["type"] = typ
                f["description"], size = clean_description(f.get("description"))
                f["dimensions"] = f.get("dimensions") or size
                rows[f["id"]] = f            # events/illustrator/tags: retag() in write_outputs
            return rows
        except Exception as e:
            log.warning(f"Could not load existing figures.json: {e}")
    return {}


def other_source_rows(own_rows: list[dict], own_source: str) -> list[dict]:
    """Rows saved by the other scrapers, minus any whose JAN barcode `own_rows` already has."""
    if not FIGURES_FILE.exists():
        return []
    try:
        saved = json.loads(FIGURES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    own_codes = {f["barcode"] for f in own_rows if f.get("barcode")}
    return [f for f in saved
            if f.get("source") not in (own_source, None) and f.get("barcode") not in own_codes]


def write_outputs(final: list[dict], new: int, mode: str) -> None:
    # Re-judge every source's rows, so classifier fixes also remove rows saved earlier
    kept = [f for f in final if classify(f.get("name", ""), f.get("manufacturer")) is not None]
    if len(kept) < len(final):
        log.info(f"Dropped {len(final) - len(kept)} saved rows the classifier now rejects.")
    final = kept
    for f in final:
        retag(f)
    save(final, {
        "total_figures": len(final),
        "new_this_run": new,
        "by_type": dict(sorted(count_by(final, lambda f: f.get("type")).items(), key=lambda x: -x[1])),
        "by_year": dict(sorted(count_by(final, lambda f: f.get("year")).items())),
        "by_event": dict(sorted(count_by(final, lambda f: f.get("events", [])).items(), key=lambda x: -x[1])),
        "by_source": count_by(final, lambda f: f.get("source")),
        "scrape_mode": mode,
    })


def save(figures: list[dict], stats: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    figures.sort(key=lambda f: (f.get("release_date") or "0000-00", f.get("name", "")), reverse=True)
    FIGURES_FILE.write_text(json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8")
    stats["last_updated"] = datetime.now(timezone.utc).isoformat()
    META_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Saved {len(figures)} figures -> {FIGURES_FILE}")


def count_by(figures: list[dict], key) -> dict:
    out: dict = {}
    for f in figures:
        for v in (key(f) if isinstance(key(f), list) else [key(f)]):
            if v is not None:
                out[str(v)] = out.get(str(v), 0) + 1
    return out


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def scrape(incremental: bool, page_limit: int | None) -> int:
    figures = load_existing()
    log.info(f"Loaded {len(figures)} existing HLJ figures.")

    # 1. Listing pages -> stubs
    stubs: dict[str, dict] = {}
    for query in LIST_QUERIES:
        for page in range(1, (page_limit or MAX_PAGES) + 1):
            body = get_html(LIST_URL.format(query=query, page=page))
            if body is None:
                break
            found = [s for s in parse_listing(body) if s["id"] not in stubs]
            log.info(f"[{query}] listing page {page}: {len(found)} new items")
            if not found:                   # past the last page
                break
            stubs.update({s["id"]: s for s in found})
            time.sleep(DELAY_BETWEEN_PAGES)
    log.info(f"Collected {len(stubs)} listing stubs.")
    if not stubs:
        log.error("No listing data fetched. Aborting without touching figures.json.")
        return 1

    # 2. Detail pages
    new = skipped = dropped = 0
    for i, (fig_id, stub) in enumerate(stubs.items(), 1):
        if incremental and fig_id in figures:
            skipped += 1
            continue
        if classify(stub["name"], None) is None:    # goods: skip without a detail fetch
            dropped += 1
            figures.pop(fig_id, None)
            continue
        log.info(f"[{i}/{len(stubs)}] {stub['name'][:70]}")
        body = get_html(stub["detail_url"])
        if body is None:
            continue
        fig = parse_detail(body, stub)
        if fig is None:
            dropped += 1
            figures.pop(fig_id, None)
        else:
            figures[fig_id] = fig
            new += 1
        time.sleep(DELAY_BETWEEN_ITEMS)

    log.info(f"Done. New/updated: {new} | Skipped: {skipped} | Not figures: {dropped}")

    hlj_rows = list(figures.values())
    final = hlj_rows + other_source_rows(hlj_rows, "hlj")
    write_outputs(final, new, "incremental" if incremental else "full")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="HLJ -> Hatsune Miku Figure Scraper")
    ap.add_argument("--incremental", action="store_true", help="Skip figures already saved")
    ap.add_argument("--limit", type=int, default=None, help="Max listing pages (testing)")
    args = ap.parse_args()
    try:
        sys.exit(scrape(args.incremental, args.limit))
    except Blocked as e:
        log.error(f"Stopping: {e}")
        sys.exit(1)
