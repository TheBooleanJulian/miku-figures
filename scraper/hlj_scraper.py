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
LIST_URL = HLJ_BASE + "/search/?Word=hatsune+miku&GenreCode2=Figures&Page={page}"
MAX_PAGES = 60                  # hard cap; listing has ~38 pages
OUTPUT_DIR = Path(__file__).parent.parent / "public"
FIGURES_FILE = OUTPUT_DIR / "figures.json"
META_FILE = OUTPUT_DIR / "meta.json"
DELAY_BETWEEN_PAGES = 1.5       # seconds — be polite
DELAY_BETWEEN_ITEMS = 0.8
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

EVENT_KEYWORDS = {
    "Snow Miku":       ["snow miku", "snow ver", "yuki miku"],
    "Racing Miku":     ["racing miku", "hatsune miku gt", "racing ver"],
    "Magical Mirai":   ["magical mirai", "magic mirai"],
    "Symphony":        ["symphony"],
    "Append":          ["append"],
    "EXPO":            ["expo", "miku expo"],
    "Deep Sea Girl":   ["deep sea girl", "kaizokunyan"],
    "Dreamy Vocal":    ["dreamy vocal"],
    "Live Stage":      ["live stage", "live concert"],
    "Mikudayo":        ["mikudayo"],
    "BEAST RINGER":    ["beast ringer"],
    "Cinnamoroll":     ["cinnamoroll"],
    "Sand Planet":     ["sand planet"],
    "World is Mine":   ["world is mine", "worldismine"],
    "Tell Your World": ["tell your world"],
    "Senbonzakura":    ["senbonzakura"],
}

ILLUSTRATORS = {
    "KEI": ["art by kei", "(kei)"], "Rella": ["rella"], "iXima": ["ixima"],
    "Fuzichoco": ["fuzichoco"], "Saine": ["saine"], "GEMI": ["gemi"],
    "Ontama": ["ontama"], "Yunomachi": ["yunomachi"], "raemz": ["raemz"],
    "azurite": ["azurite"], "Mikatan": ["mikatan"],
}

SCALE_RE = re.compile(r"\b1/(\d+)\b")


# Goods that HLJ files under "Figures" but that aren't figures.
MERCH_RE = re.compile(
    r"tapestr|towel|t-shirt|\bt shirt|jersey|key ?chain|\bcase\b|code clip|\bplate\b|"
    r"costume set|\btote\b|sticker|poster|\bmug\b|\bcup\b|\bbags?\b|backpack|hoodie|sweatshirt|"
    r"parka|acrylic|badge|clear file|blanket|pouch|notebook|cushion|umbrella|wallet|"
    r"smartphone|\bpins?\b|calendar|luggage|mirror|shikishi|ticket|rubber mat|puzzle|card holder|hanging scroll|amulet|otamatone|\[used item",
    re.I,
)
# Another Vocaloid is the actual product (e.g. "... Kurumitapinui MEIKO")
OTHER_CHARACTER_RE = re.compile(
    r"(meiko|kaito|(rin|len) kagamine|kagamine (rin|len)|luka megurine|megurine luka)\)?$", re.I)
PLUSH_RE = re.compile(r"plush|mascot|nui|kurumi|chibigurumi|fluffy|fuwa|yurayura|swaying", re.I)
PRIZE_RE = re.compile(
    r"amp\+?|noodle stopper|wonderland|exceed creative|trio-try-it|luminasta|espresto|"
    r"sweet sweets|fuwapuchi|figure|^pm|4\.5 chan|look up|artist collaboration",
    re.I,
)
PRIZE_MAKERS = ("taito", "furyu", "sega", "banpresto", "bandai spirits", "bandai namco")


def classify(name: str, maker: str | None) -> str | None:
    """Figure type for a product, or None if it is merchandise / not a Miku figure."""
    if "miku" not in name.lower() or MERCH_RE.search(name) or OTHER_CHARACTER_RE.search(name.strip()):
        return None
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
    for artist, kws in ILLUSTRATORS.items():
        if any(k in low for k in kws):
            return artist
    return None


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
    if "kit" in item_type.lower():          # model kits (e.g. Nendoroid Plamo) aren't figures
        return None

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

    size = re.search(r"(?:Figure Size|Size)[:\s]*(?:Approximately|Approx\.?)?\s*([\d.]+\s?(?:cm|mm)[^<\n]{0,20})",
                     page_html, re.I)
    scale_m = SCALE_RE.search(name)

    events = extract_events(name)
    series = _li(page_html, "Series")

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
        "description": (ld.get("description") or "").strip(),
        "dimensions": size.group(1).strip() if size else None,
        "material": None,
        "barcode": ld.get("gtin13") or _li(page_html, "JAN Code"),
        "mfc_owned_count": None,
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
                typ = classify(f.get("name", ""), f.get("manufacturer"))
                if typ is None:             # rules changed: drop goods saved earlier
                    continue
                f["type"] = typ
                f["tags"] = [typ, *f.get("events", []), *[t for t in f.get("tags", [])[1:] if t not in (typ,)]]
                rows[f["id"]] = f
            return rows
        except Exception as e:
            log.warning(f"Could not load existing figures.json: {e}")
    return {}


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
    for page in range(1, (page_limit or MAX_PAGES) + 1):
        body = get_html(LIST_URL.format(page=page))
        if body is None:
            break
        found = [s for s in parse_listing(body) if s["id"] not in stubs]
        log.info(f"Listing page {page}: {len(found)} new items")
        if not found:                       # past the last page
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
        log.info(f"[{i}/{len(stubs)}] {stub['name'][:70]}")
        body = get_html(stub["detail_url"])
        if body is None:
            continue
        fig = parse_detail(body, stub)
        if fig is None:
            dropped += 1
        else:
            figures[fig_id] = fig
            new += 1
        time.sleep(DELAY_BETWEEN_ITEMS)

    log.info(f"Done. New/updated: {new} | Skipped: {skipped} | Not figures: {dropped}")

    final = list(figures.values())
    save(final, {
        "total_figures": len(final),
        "new_this_run": new,
        "by_type": dict(sorted(count_by(final, lambda f: f.get("type")).items(), key=lambda x: -x[1])),
        "by_year": dict(sorted(count_by(final, lambda f: f.get("year")).items())),
        "by_event": dict(sorted(count_by(final, lambda f: f.get("events", [])).items(), key=lambda x: -x[1])),
        "scrape_mode": "incremental" if incremental else "full",
        "source": "hlj.com",
    })
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
