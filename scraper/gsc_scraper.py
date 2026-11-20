#!/usr/bin/env python3
"""
Good Smile Company scraper — adds Hatsune Miku figures from goodsmile.com (official, JPY).
=========================================================================================
goodsmile.com is the maker's own catalogue (Good Smile Company, Max Factory, FREEing,
...), back to the early figures, with each product's JAN, retail price and release
dates. It has no robots.txt and no sitemap; its search page loads results from
/en/search/list (60 per page, HTML), the endpoint the page's own "See more" button
calls. This scraper reads that list for the keyword "miku", then fetches only the
product pages whose titles pass the classifier, slowly. robots.txt is still checked
every run, so a rule the site adds later is obeyed. Standard library only; reuses
the HLJ scraper's classifier and storage and the Nin-Nin-Game scraper's robots and
duplicate checks.

Only facts are stored (name, maker, series, JAN, price, dates, size, image link);
the site's description text is not copied.

Usage:
    python gsc_scraper.py            # fetch up to MAX_NEW new product pages
    python gsc_scraper.py --max 10   # fetch at most 10 (dev/test)

Rows are written to ../public/figures.json with source="gsc". A product whose JAN
(original or rerelease) another source already has is skipped; goods and
duplicates are remembered in gsc_skip.json.
"""

import argparse
import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import hlj_scraper as h
import latendo_scraper as L
import ninnin_scraper as N
from hlj_scraper import log

BASE = "https://www.goodsmile.com"
LIST_URL = BASE + "/en/search/list?{query}"
PRODUCT_URL = BASE + "/en/product/{pid}"
KEYWORD = "miku"
PAGE_SIZE = 60                   # what the site's own "See more" button requests
MAX_PAGES = 30                   # "miku" had ~900 results (15 pages) in 2026-11
MAX_NEW = 300                    # product pages fetched per run
DELAY = 3.0                      # seconds between requests
MAX_FAILURES = 8                 # consecutive failures before ending the run
SKIP_FILE = Path(__file__).parent / "gsc_skip.json"       # product ids known to be goods/duplicates

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; miku-figures-archive; "
                  "+https://github.com/TheBooleanJulian/miku-figures)",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}

# The search page's default filter, with online-exclusives no longer the only results
FILTER = {"search_keyword": KEYWORD, "search_over18": False, "search_category": [], "search_maker": [],
          "search_title": [], "search_status": "", "release_date_from": "", "release_date_to": "",
          "search_bonus": False, "search_exclusive": False, "search_sale": False,
          "search_sales_origin": False, "tag": []}

ITEM_RE = re.compile(r'<a class="p-product-list__link" href="/en/product/(\d+)".*?'
                     r'<h2 class="c-title c-title--level8">(.*?)</h2>', re.S)
VARIANTS_RE = re.compile(r"let variants?\w*\s*=\s*(\[.*?\]);\s*(?:let|const|var|\n|<)", re.S)
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
SPEC_RE = re.compile(r'<dt class="b-outline-table__term">(.*?)</dt>\s*<dd class="b-outline-table__desc">(.*?)</dd>', re.S)
AVAILABLE_RE = re.compile(r"Available:\s*(\d{1,2})/(\d{4})")
GSC_SCALE_RE = re.compile(r"\b1/(\d+)(?:st|nd|rd|th)?\b")
HEIGHT_RE = re.compile(r"approximately\s+([\d.,]+\s*(?:mm|cm))(?:\s+in\s+(?:height|length|width))?", re.I)
MATERIAL_RE = re.compile(r"\bpainted\s+(.+?)\s+(?:non-scale|1/\d|scale|articulated|figure|complete)", re.I)
# GSC categories that are plainly not figures
NON_FIGURE_CAT_RE = re.compile(
    r"apparel|goods|accessor|stationer|tapestr|acrylic|book|music|\bcd\b|dvd|blu-?ray|game|card|"
    r"plastic model|model kit|moderoid|plamatea|tableware|bag|towel|cushion|figure stand|display", re.I)


class Stop(Exception):
    """Rate limited, disallowed or failing repeatedly: end the run and keep progress."""


_failures = 0
_rules: list[tuple[bool, str]] = []


def fetch(url: str, allow_404: bool = False) -> str | None:
    global _failures
    if not N.robots_allows(url, _rules):
        raise Stop(f"robots.txt disallows {url}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
            data = r.read()
        _failures = 0
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if allow_404 and e.code == 404:
            return None
        log.warning(f"HTTP {e.code} for {url}")
        if e.code in (403, 429):
            raise Stop(f"HTTP {e.code} from goodsmile.com at {url}")
    except Exception as e:
        log.warning(f"{type(e).__name__} for {url}: {e}")
    _failures += 1
    if _failures >= MAX_FAILURES:
        raise Stop(f"{_failures} consecutive failures, last: {url}")
    return None


def load_robots() -> None:
    """No robots.txt (404) means no restrictions; anything else that fails stops the run."""
    global _rules
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + "/robots.txt", headers=HEADERS),
                                    timeout=30) as r:
            data = r.read()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        _rules = N.robots_rules(data.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise Stop(f"robots.txt returned HTTP {e.code}")
        _rules = []
    except Exception as e:
        raise Stop(f"could not read robots.txt: {e}")


def list_products(page_limit: int) -> list[tuple[str, str]]:
    """(product id, title) of every search result for KEYWORD."""
    found: dict[str, str] = {}
    for page in range(page_limit):
        query = urllib.parse.urlencode({
            "filter": json.dumps(FILTER, separators=(",", ":")), "orderBy": 1, "limit": PAGE_SIZE,
            "offset": page * PAGE_SIZE, "couponId": "null", "searchIndex": -1})
        time.sleep(DELAY)
        body = fetch(LIST_URL.format(query=query))
        if body is None:
            break
        items = [(pid, html.unescape(re.sub(r"<[^>]+>", "", t)).strip()) for pid, t in ITEM_RE.findall(body)]
        new = [(pid, t) for pid, t in items if pid not in found]
        log.info(f"List page {page + 1}: {len(new)} new products")
        if not new:
            break
        found.update(new)
    return list(found.items())


# ──────────────────────────────────────────────
# PRODUCT PAGE
# ──────────────────────────────────────────────

def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_product(page: str, pid: str) -> dict | None:
    """Row for a product page, or None when it is not a Miku figure."""
    m = VARIANTS_RE.search(page)
    try:
        variants = json.loads(m.group(1)) if m else []
    except ValueError:
        variants = []
    if not variants:
        return None
    # The original release, not a rerelease ("type": "resale")
    base = next((v for v in variants if str(v.get("parentProductCode")) == pid), None) \
        or next((v for v in variants if v.get("type") != "resale"), variants[-1])

    name = html.unescape(base.get("name") or "").strip()
    maker = (base.get("manufacturer") or "").strip() or None
    categories = [c for c in (base.get("categories") or []) if isinstance(c, str)]
    if not name or any(NON_FIGURE_CAT_RE.search(c) for c in categories) or L.KIT_RE.search(name):
        return None
    series = (base.get("work") or "").strip() or None
    if series and not re.search(r"miku|vocaloid|project sekai|colorful stage|piapro|project diva|"
                                r"project mirai|magical mirai|racing", series, re.I) \
            and not h.VOCALOID_NAME_RE.search(name):
        return None                                  # another franchise's "Miku"
    typ = h.classify(name, maker)
    if typ is None:
        return None

    specs = {_clean(dt).lower(): _clean(dd) for dt, dd in SPEC_RE.findall(page)}
    spec = base.get("spec") or specs.get("specifications") or ""
    scale_m = GSC_SCALE_RE.search(name) or GSC_SCALE_RE.search(spec)
    low_cat = " ".join(categories).lower()
    if typ == "Other":
        if "plush" in low_cat:
            typ = "Plush / Soft"
        elif "pop up parade" in low_cat:
            typ = "Pop Up Parade"
        elif "figma" in low_cat:
            typ = "Figma"
        elif "nendoroid" in low_cat:
            typ = "Nendoroid"
        elif scale_m or "scale" in low_cat:
            typ = "Scale"

    # Original release month: "[Available: 11/2015][Rerelease:10/2024]", else the variant's date
    release = None
    if am := AVAILABLE_RE.search(specs.get("related information", "")):
        release = f"{am.group(2)}-{int(am.group(1)):02d}"
    elif rd := re.match(r"(\d{4})-(\d{2})", base.get("releaseDate") or ""):
        release = f"{rd.group(1)}-{rd.group(2)}"

    image = None
    for block in LD_RE.findall(page):
        try:
            ld = json.loads(block)
        except ValueError:
            continue
        if isinstance(ld, dict) and ld.get("@type") == "Product":
            image = ld.get("image")
            break
    if isinstance(image, list):
        image = image[0] if image else None
    if image and image.startswith("/"):
        image = BASE + image

    jans = [str(v.get("jan") or "").strip() for v in variants]
    jans = [j for j in dict.fromkeys(jans) if re.fullmatch(r"\d{8,14}", j)]
    base_jan = str(base.get("jan") or "").strip()
    price = base.get("retailPriceInTax")
    height = HEIGHT_RE.search(spec)
    material = MATERIAL_RE.search(spec)

    return {
        "id": "GS" + pid,
        "name": name,
        "manufacturer": maker,
        "release_date": release,
        "year": int(release[:4]) if release else None,
        "type": typ,
        "scale": f"1/{scale_m.group(1)}" if scale_m else None,
        "price_jpy": int(price) if isinstance(price, (int, float)) and price > 0 else None,
        "price_sgd": None,
        "price_usd": None,
        "image_url": image,
        "detail_url": PRODUCT_URL.format(pid=pid),
        "events": [],                                # filled by h.retag()
        "illustrator": None,
        "tags": [],
        "description": "",                           # not copied: the site's own text
        "dimensions": height.group(1).replace(" ", "") if height else None,
        "material": material.group(1) if material else None,
        "barcode": base_jan if base_jan in jans else (jans[0] if jans else None),
        "jans": jans,                                # every variant's JAN, for duplicate checks
        "mfc_owned_count": None,
        "series": series,
        "category": ", ".join(categories) or None,
        "item_type": None,
        "source": "gsc",
        "handle": pid,
    }


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def duplicate(row: dict, others: N.Others) -> bool:
    if any(j in others.codes for j in row.get("jans") or []):
        return True
    return others.has(row)


def main(max_new: int, page_limit: int) -> int:
    saved = json.loads(h.FIGURES_FILE.read_text(encoding="utf-8")) if h.FIGURES_FILE.exists() else []
    others_rows = [f for f in saved if f.get("source") != "gsc"]
    others = N.Others(others_rows)
    skip = set(json.loads(SKIP_FILE.read_text())) if SKIP_FILE.exists() else set()

    # Re-judge saved rows: another source picking a figure up keeps theirs
    mine: dict[str, dict] = {}
    for f in (f for f in saved if f.get("source") == "gsc"):
        if duplicate(f, others):
            log.info(f"Dropping saved row: {f['name'][:60]}")
            skip.add(f["id"])
        else:
            mine[f["id"]] = f
    log.info(f"Loaded {len(mine)} GSC rows, {len(others_rows)} from other sources, {len(skip)} skipped ids.")

    new = skipped = 0
    try:
        load_robots()
        products = list_products(page_limit)
        todo = [(pid, title) for pid, title in products
                if "GS" + pid not in mine and "GS" + pid not in skip and h.classify(title, None) is not None]
        log.info(f"{len(products)} '{KEYWORD}' products; {len(todo)} to fetch (cap {max_new}).")
        for i, (pid, _title) in enumerate(todo[:max_new], 1):
            time.sleep(DELAY)
            page = fetch(PRODUCT_URL.format(pid=pid))
            if page is None:
                continue
            row = parse_product(page, pid)
            if row is None or duplicate(row, others) or N.own_match(row, mine):
                skip.add("GS" + pid)                 # goods, or already carried
                skipped += 1
                continue
            mine[row["id"]] = row
            new += 1
            if i % 25 == 0:
                log.info(f"[{i}/{min(len(todo), max_new)}] {row['name'][:60]}")
    except Stop as e:
        log.warning(f"Ending the run early and keeping progress ({e}).")

    SKIP_FILE.write_text(json.dumps(sorted(skip)))
    log.info(f"Done. New: {new} | Skipped (goods/duplicates): {skipped} | GSC rows: {len(mine)}")
    h.write_outputs(others_rows + list(mine.values()), new, "gsc")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Good Smile Company -> Hatsune Miku Figure Scraper")
    ap.add_argument("--max", type=int, default=MAX_NEW, help="Max product pages to fetch")
    ap.add_argument("--pages", type=int, default=MAX_PAGES, help="Max list pages (testing)")
    args = ap.parse_args()
    sys.exit(main(args.max, args.pages))
