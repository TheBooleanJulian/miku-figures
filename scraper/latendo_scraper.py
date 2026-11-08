#!/usr/bin/env python3
"""
Latendo scraper — adds Hatsune Miku figures from latendo.com (Singapore, SGD).
==============================================================================
Latendo is an Odoo store. Its robots.txt disallows shop search, pagination and
category filters, so this scraper never browses the shop: it reads the sitemap
(allowed), keeps product URLs whose slug mentions Miku, and fetches only those
product pages, slowly. Standard library only; reuses the HLJ scraper's
classifier, tagging and storage.

Usage:
    python latendo_scraper.py             # fetch up to MAX_NEW new products
    python latendo_scraper.py --max 10    # fetch at most 10 (dev/test)

Rows are written to ../public/figures.json with source="latendo". Latendo shows
no JAN barcode, so duplicates of HLJ / Solaris rows are found by name instead
(see same_figure); those, and goods, are remembered in latendo_skip.json.
Pre-orders ("(PO)") are kept: the archive lists announced figures too.
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import hlj_scraper as h
from hlj_scraper import log

BASE = "https://www.latendo.com"
SITEMAP_URL = BASE + "/sitemap.xml"
MAX_NEW = 200                    # product pages fetched per run; the backlog clears over a few daily runs
DELAY = 3.0                      # seconds between requests
MAX_FAILURES = 8                 # consecutive failures (or 429s) before ending the run
SKIP_FILE = Path(__file__).parent / "latendo_skip.json"   # slugs known to be goods/duplicates

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; miku-figures-archive; "
                  "+https://github.com/TheBooleanJulian/miku-figures)",
    "Accept-Language": "en-US,en;q=0.9",
}

SLUG_RE = re.compile(r"<loc>https://www\.latendo\.com/shop/([a-z0-9-]*miku[a-z0-9-]*-\d+)</loc>")
# Latendo categories that are plainly not figures ("Complete Figure", "Plush" and
# oddities like "Genesis" pass; the name classifier then judges the rest).
NON_FIGURE_CAT_RE = re.compile(
    r"accessor|card|apparel|cloth|stationer|book|music|\bcd\b|dvd|blu-?ray|game|poster|"
    r"\bbag|household|kitchen|\bkit\b|model kit|plastic model", re.I)
# "(PO) ", "(GF) ", "(SA) " order-type prefixes on titles
PREFIX_RE = re.compile(r"^\s*(?:\([A-Z]{1,4}\)\s*)+")


class Stop(Exception):
    """Rate limited or failing repeatedly: end the run and keep progress."""


_failures = 0


def fetch(url: str) -> str | None:
    global _failures
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
            _failures = 0
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        log.warning(f"HTTP {e.code} for {url}")
        if e.code == 429:
            raise Stop(f"429 from Latendo at {url}")
    except Exception as e:
        log.warning(f"{type(e).__name__} for {url}: {e}")
    _failures += 1
    if _failures >= MAX_FAILURES:
        raise Stop(f"{_failures} consecutive failures, last: {url}")
    return None


def slug_name(slug: str) -> str:
    """Rough product name from a URL slug, for pre-filtering goods before a fetch."""
    words = slug.split("-")[:-1]                     # drop the trailing product id
    if words and words[0] in ("po", "gf", "sa"):     # order-type prefix
        words = words[1:]
    return " ".join(words)


# ──────────────────────────────────────────────
# DUPLICATE DETECTION (no barcodes on Latendo)
# ──────────────────────────────────────────────

# Words that differ between retailers' titles for the same product
NOISE = {
    "hatsune", "miku", "character", "vocal", "series", "ver", "version", "figure",
    "complete", "pvc", "statue", "scale", "non", "the", "and", "of", "x", "re", "issue",
    "reissue", "rerelease", "release", "rerun", "run", "edition", "box", "po", "gf", "sa",
    "good", "smile", "company", "gsc", "max", "factory", "exclusive", "shop", "with",
}
# Product lines that are never the same item as a figure of another type
DISTINCT_TYPES = {"Nendoroid", "Figma", "Pop Up Parade", "Plush / Soft", "Mini / Petite"}
MATCH_THRESHOLD = 0.75           # share of distinct title words two names must have in common
KIT_RE = re.compile(r"plamatea|moderoid|plastic model|model kit", re.I)


def name_tokens(name: str) -> tuple[frozenset[str], frozenset[str]]:
    """(all title words, identifier words) of a name, normalised across retailers.

    Identifiers are numbers and single letters (years, "MC-06", variant "A"/"B");
    match_key adds the series/events. Two titles only match when these agree exactly.
    """
    low = PREFIX_RE.sub("", html.unescape(name)).lower()
    low = h.SCALE_RE.sub(" ", low)
    low = re.sub(r"character vocal series 0?1", " ", low)
    low = re.sub(r"\b(nendoroid|figma)\s+(?:sp-?\s*)?#?\d+\b", r"\1", low)   # catalogue numbers
    low = re.sub(r"#\d+", " ", low)
    low = re.sub(r"\bm size", "msize", low)
    low = re.sub(r"['’]", "", low)
    words = []
    for w in re.findall(r"[a-z]+|\d+", low):
        if w not in NOISE:
            words.append(str(int(w)) if w.isdigit() else w)
    ids = frozenset(w for w in words if w.isdigit() or len(w) == 1)
    return frozenset(words), ids


def match_key(f: dict) -> tuple:
    name = f.get("name", "")
    words, ids = name_tokens(name)
    ids |= frozenset(h.extract_events(name))         # "Snow Miku" vs "Racing Miku" blind boxes
    return words, ids, f.get("scale"), f.get("type")


def same_figure(a: tuple, b: tuple) -> bool:
    """True when two match_key()s very probably name the same product."""
    (wa, ia, sa, ya), (wb, ib, sb, yb) = a, b
    if not wa or not wb or ia != ib:
        return False
    if sa and sb and sa != sb:
        return False
    if ya != yb and (ya in DISTINCT_TYPES or yb in DISTINCT_TYPES):
        return False
    return len(wa & wb) / len(wa | wb) >= MATCH_THRESHOLD


def find_duplicate(row: dict, others: list[tuple]) -> bool:
    key = match_key(row)
    return any(same_figure(key, k) for k in others)


# ──────────────────────────────────────────────
# PRODUCT PAGE
# ──────────────────────────────────────────────

def _meta(page: str, prop: str) -> str | None:
    m = re.search(rf'<meta property="og:{prop}" content="([^"]*)"', page)
    return html.unescape(m.group(1)).strip() if m else None


def _spec(page: str, label: str) -> str | None:
    """Value of a "Label: <span>value</span>" line in the product meta block."""
    m = re.search(rf"{re.escape(label)}:\s*<span>(.*?)</span>", page, re.S)
    if not m:
        return None
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() or None


def parse_product(page: str, slug: str) -> dict | None:
    """Row for a product page, or None when it is not a Miku figure."""
    title = _meta(page, "title")
    if not title:
        return None
    brand = _spec(page, "Brand")
    category = _spec(page, "Category") or ""
    series = _spec(page, "Series")
    size = _spec(page, "Size")
    if NON_FIGURE_CAT_RE.search(category) or KIT_RE.search(title):
        return None

    name = PREFIX_RE.sub("", title)
    if brand:                                        # "(Good Smile Company) HELLO! GOOD SMILE ..."
        name = re.sub(rf"^\(\s*{re.escape(brand)}\s*\)\s*", "", name, flags=re.I)
    if series and not re.search(r"miku|vocaloid|project sekai", series, re.I) \
            and not h.VOCALOID_NAME_RE.search(name):
        return None                                  # another franchise's "Miku"
    typ = h.classify(name, brand)
    if typ is None:
        return None
    scale_m = h.SCALE_RE.search(size or "") or h.SCALE_RE.search(name)
    low_cat = category.lower()
    if "plush" in low_cat and typ in ("Other", "Prize"):
        typ = "Plush / Soft"
    elif "prize" in low_cat and typ == "Other":
        typ = "Prize"
    elif "trading" in low_cat and typ == "Other":   # blind boxes ("Trading Figure")
        typ = "Mini / Petite"
    elif scale_m and typ == "Other":                 # Latendo puts the scale in Size, not the title
        typ = "Scale"

    dims = None
    if size:
        dims = re.sub(r"\b1/\d+\b\s*(?:scale)?", "", size, flags=re.I).strip(" ()") or None

    release = None
    rd = _spec(page, "Release Date")
    if rd and (dm := re.match(r"(\d{4})-(\d{2})", rd)):
        release = f"{dm.group(1)}-{dm.group(2)}"

    price = None
    pm = re.search(r'itemprop="price"[^>]*>\s*([\d.,]+)', page)
    cm = re.search(r'itemprop="priceCurrency"[^>]*>\s*([A-Z]{3})', page)
    if pm and (cm is None or cm.group(1) == "SGD"):
        try:
            price = float(pm.group(1).replace(",", ""))
        except ValueError:
            pass

    return {
        "id": "LT" + slug.rsplit("-", 1)[-1],
        "name": name.strip(),
        "manufacturer": brand,
        "release_date": release,
        "year": int(release[:4]) if release else None,
        "type": typ,
        "scale": f"1/{scale_m.group(1)}" if scale_m else None,
        "price_jpy": None,
        "price_sgd": price,
        "price_usd": None,
        "image_url": _meta(page, "image"),
        "detail_url": f"{BASE}/shop/{slug}",
        "events": [],                                # filled by h.retag()
        "illustrator": None,
        "tags": [],
        "description": "",
        "dimensions": dims,
        "material": None,
        "barcode": None,
        "mfc_owned_count": None,
        "series": series,
        "category": category or None,
        "item_type": None,
        "source": "latendo",
        "handle": slug,
    }


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main(max_new: int) -> int:
    saved = json.loads(h.FIGURES_FILE.read_text(encoding="utf-8")) if h.FIGURES_FILE.exists() else []
    mine = {f["handle"]: f for f in saved if f.get("source") == "latendo" and f.get("handle")}
    others = [f for f in saved if f.get("source") != "latendo"]
    other_keys = [match_key(f) for f in others]
    skip = set(json.loads(SKIP_FILE.read_text())) if SKIP_FILE.exists() else set()
    log.info(f"Loaded {len(mine)} Latendo rows, {len(others)} from other sources, {len(skip)} skipped slugs.")

    # Another source may have picked up a figure since we saved it: keep theirs.
    for slug in [s for s, f in mine.items() if find_duplicate(f, other_keys)]:
        log.info(f"Now carried by another source, dropping: {mine[slug]['name'][:60]}")
        del mine[slug]
        skip.add(slug)

    new = skipped = 0
    try:
        sitemap = fetch(SITEMAP_URL)
        if sitemap is None:
            log.error("Could not fetch the Latendo sitemap; leaving Latendo rows as they are.")
        else:
            slugs = list(dict.fromkeys(SLUG_RE.findall(sitemap)))
            todo = [s for s in slugs
                    if s not in mine and s not in skip and h.classify(slug_name(s), None) is not None]
            log.info(f"{len(slugs)} Miku product URLs; {len(todo)} to fetch (cap {max_new}).")
            for i, slug in enumerate(todo[:max_new], 1):
                time.sleep(DELAY)
                page = fetch(f"{BASE}/shop/{slug}")
                if page is None:
                    continue
                row = parse_product(page, slug)
                if row is None or find_duplicate(row, other_keys):
                    skip.add(slug)                   # goods, or already carried by another source
                    skipped += 1
                    continue
                mine[slug] = row
                new += 1
                if i % 25 == 0:
                    log.info(f"[{i}/{min(len(todo), max_new)}] {row['name'][:60]}")
    except Stop as e:
        log.warning(f"Ending the run early and keeping progress ({e}).")

    SKIP_FILE.write_text(json.dumps(sorted(skip)))
    log.info(f"Done. New: {new} | Skipped (goods/duplicates): {skipped}")
    h.write_outputs(others + list(mine.values()), new, "latendo")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Latendo -> Hatsune Miku Figure Scraper")
    ap.add_argument("--max", type=int, default=MAX_NEW, help="Max product pages to fetch")
    sys.exit(main(ap.parse_args().max))
