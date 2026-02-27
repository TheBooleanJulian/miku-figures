#!/usr/bin/env python3
"""
MFC Scraper — Hatsune Miku Figure Archive
==========================================
Scrapes MyFigureCollection.net for all Hatsune Miku figures.
Hatsune Miku character ID on MFC: 2156

Usage:
    python mfc_scraper.py                   # full scrape → figures.json
    python mfc_scraper.py --incremental     # only fetch pages newer than last run
    python mfc_scraper.py --limit 5         # scrape first 5 pages (dev/test)

Output:
    ../public/figures.json
    ../public/meta.json      ← scrape metadata / stats
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

MFC_BASE       = "https://myfigurecollection.net"
MFC_BROWSE     = f"{MFC_BASE}/browse.v4.php"
MFC_CHAR_ID    = 2156          # Hatsune Miku's MFC character ID
PAGE_SIZE      = 48            # MFC default items per page
OUTPUT_DIR     = Path(__file__).parent.parent / "public"
FIGURES_FILE   = OUTPUT_DIR / "figures.json"
META_FILE      = OUTPUT_DIR / "meta.json"
DELAY_BETWEEN_PAGES   = 1.5   # seconds — be a polite scraper
DELAY_BETWEEN_ITEMS   = 0.4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": "https://myfigurecollection.net/",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# ──────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("mfc-scraper")

# ──────────────────────────────────────────────
# TYPE / CATEGORY NORMALISATION
# ──────────────────────────────────────────────

TYPE_MAP = {
    "scale":         "Scale",
    "1/":            "Scale",
    "nendoroid":     "Nendoroid",
    "figma":         "Figma",
    "prize":         "Prize",
    "pm figure":     "Prize",
    "spm":           "Prize",
    "taito":         "Prize",
    "sega":          "Prize",
    "furyu":         "Prize",
    "banpresto":     "Prize",
    "luminasta":     "Prize",
    "pop up parade": "Pop Up Parade",
    "pup":           "Pop Up Parade",
    "petit":         "Mini / Petite",
    "mini":          "Mini / Petite",
    "trading":       "Mini / Petite",
    "chibi":         "Mini / Petite",
    "figfix":        "Mini / Petite",
    "plush":         "Plush / Soft",
    "soft":          "Plush / Soft",
    "doll":          "Doll / BJD",
    "dollfie":       "Doll / BJD",
    "pullip":        "Doll / BJD",
    "bust":          "Bust",
    "garage kit":    "Garage Kit",
    "gk":            "Garage Kit",
    "resin":         "Garage Kit",
    "figural":       "Other",
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
    "BEAST RINGER":    ["beast ringer", "beast"],
    "Cinnamoroll":     ["cinnamoroll"],
    "Sand Planet":     ["sand planet"],
    "World is Mine":   ["world is mine", "worldismine"],
    "Tell Your World": ["tell your world"],
    "Senbonzakura":    ["senbonzakura"],
    "Luka×Miku":       ["luka"],
}

ILLUSTRATORS = {
    "KEI":        ["kei", "(kei)"],
    "Rella":      ["rella"],
    "iXima":      ["ixima"],
    "Fuzichoco":  ["fuzichoco"],
    "Saine":      ["saine"],
    "GEMI":       ["gemi"],
    "Ontama":     ["ontama"],
    "Yunomachi":  ["yunomachi"],
    "raemz":      ["raemz"],
    "azurite":    ["azurite"],
    "Mikatan":    ["mikatan"],
    "TAMA":       ["tama"],
}

SCALE_PATTERN = re.compile(r"1/(\d+)", re.IGNORECASE)
PRICE_PATTERN = re.compile(r"[¥￥]?\s*([\d,]+)")
DATE_PATTERN  = re.compile(r"(\d{4})[-/](\d{2})")


def normalize_type(name: str, category: str = "") -> str:
    text = (name + " " + category).lower()
    for key, label in TYPE_MAP.items():
        if key in text:
            return label
    return "Other"


def extract_events(name: str) -> list[str]:
    name_lower = name.lower()
    return [event for event, kws in EVENT_KEYWORDS.items() if any(kw in name_lower for kw in kws)]


def extract_illustrator(name: str, desc: str = "") -> str | None:
    text = (name + " " + desc).lower()
    for artist, kws in ILLUSTRATORS.items():
        if any(kw in text for kw in kws):
            return artist
    return None


def extract_scale(name: str, category: str = "") -> str | None:
    text = name + " " + category
    m = SCALE_PATTERN.search(text)
    if m:
        return f"1/{m.group(1)}"
    return None


def clean_price(text: str) -> int | None:
    m = PRICE_PATTERN.search(text.replace(",", ""))
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def clean_date(text: str) -> str | None:
    m = DATE_PATTERN.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    if re.match(r"^\d{4}$", text.strip()):
        return f"{text.strip()}-01"
    return None


# ──────────────────────────────────────────────
# HTTP HELPERS
# ──────────────────────────────────────────────

session = requests.Session()
session.headers.update(HEADERS)


def get_page(url: str, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            log.warning(f"Attempt {attempt + 1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    log.error(f"Failed to fetch: {url}")
    return None


# ──────────────────────────────────────────────
# MFC BROWSE PAGE PARSER
# ──────────────────────────────────────────────

def build_browse_url(offset: int = 0, order: str = "release_date_asc") -> str:
    params = {
        "type":       -1,          # all figure types
        "characters": MFC_CHAR_ID,
        "current":    offset,
        "rootId":     0,
        "mode":       "main",
        "order":      order,
    }
    return f"{MFC_BROWSE}?{urlencode(params)}"


def parse_browse_page(soup: BeautifulSoup) -> tuple[list[dict], int]:
    """
    Returns (list_of_stub_dicts, total_count)
    stub_dicts have: id, name, image_url, detail_url, manufacturer, release_date, category
    """
    stubs = []

    # Total count from pagination header
    total = 0
    count_el = soup.select_one(".results-count, .count-info, .listing-count")
    if count_el:
        nums = re.findall(r"\d+", count_el.get_text())
        if nums:
            total = int(nums[-1])

    # Figure items — MFC uses .item-icon or .listing-item etc.
    items = soup.select(".item-icon, .figure-listing-item, div.listing div.item")
    if not items:
        # fallback: any element with a mfc figure link
        items = soup.select("a[href*='/figure/']")

    for el in items:
        # If we got anchor tags directly, wrap lookup
        anchor = el if el.name == "a" else el.select_one("a[href*='/figure/']")
        if not anchor:
            continue

        href = anchor.get("href", "")
        if "/figure/" not in href:
            continue
        detail_url = urljoin(MFC_BASE, href)

        # Figure ID from URL
        fig_id_match = re.search(r"/figure/(\d+)", href)
        fig_id = fig_id_match.group(1) if fig_id_match else None

        # Name
        name = (
            anchor.get("title")
            or el.select_one(".item-title, .figure-name, .title")
            and el.select_one(".item-title, .figure-name, .title").get_text(strip=True)
            or anchor.get_text(strip=True)
            or "Unknown Figure"
        )

        # Thumbnail
        img_el = el.select_one("img[src*='figure'], img[src*='myfigurecollection']") or el.select_one("img")
        image_url = None
        if img_el:
            src = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src")
            if src:
                # upgrade to medium/large res if possible
                image_url = src.replace("/thumb/", "/medium/").replace("_s.", "_m.")
                if not image_url.startswith("http"):
                    image_url = urljoin(MFC_BASE, image_url)

        # Manufacturer / release date on listing (sometimes shown)
        maker_el  = el.select_one(".company-name, .maker, .manufacturer")
        date_el   = el.select_one(".release-date, .date, .figure-date")
        cat_el    = el.select_one(".category, .type, .figure-type")

        stubs.append({
            "id":           fig_id,
            "name":         name.strip(),
            "detail_url":   detail_url,
            "image_url":    image_url,
            "manufacturer": maker_el.get_text(strip=True) if maker_el else None,
            "release_date": clean_date(date_el.get_text()) if date_el else None,
            "category":     cat_el.get_text(strip=True) if cat_el else None,
        })

    return stubs, total


# ──────────────────────────────────────────────
# MFC DETAIL PAGE PARSER
# ──────────────────────────────────────────────

def parse_detail_page(soup: BeautifulSoup, stub: dict) -> dict:
    """Enrich a stub with data from the detail page."""
    data = dict(stub)

    def text_of(selector: str) -> str:
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else ""

    # High-res image
    hires = soup.select_one("img.main-image, .figure-photo img, #item-image img, .product-image img")
    if hires:
        src = hires.get("src") or hires.get("data-src") or ""
        if src and src.startswith("http"):
            data["image_url"] = src
        elif src:
            data["image_url"] = urljoin(MFC_BASE, src)

    # Try og:image as fallback
    og = soup.find("meta", property="og:image")
    if og and not data.get("image_url"):
        data["image_url"] = og.get("content")

    # Structured specs table / dl list
    specs = {}
    # dl definition list (common MFC layout)
    for dt in soup.select("dl dt, .data-row .label, .spec-label"):
        dd = dt.find_next_sibling("dd") or dt.find_next_sibling(".value") or dt.find_next_sibling(".spec-value")
        if dd:
            specs[dt.get_text(strip=True).lower().rstrip(":")] = dd.get_text(strip=True)

    # table layout
    for row in soup.select("table.item-data tr, .product-specs tr, .figure-specs tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            specs[cells[0].get_text(strip=True).lower().rstrip(":")] = cells[1].get_text(strip=True)

    # Extract fields from specs
    if not data.get("manufacturer"):
        data["manufacturer"] = (
            specs.get("company") or specs.get("manufacturer") or
            specs.get("maker") or specs.get("brand") or "Unknown"
        )

    if not data.get("release_date"):
        raw_date = specs.get("release date") or specs.get("release") or specs.get("date") or ""
        data["release_date"] = clean_date(raw_date)

    category_raw = (
        specs.get("category") or specs.get("type") or
        specs.get("figure type") or data.get("category") or ""
    )
    data["category"] = category_raw

    # Scale
    scale_raw = specs.get("scale") or specs.get("size") or ""
    data["scale"] = extract_scale(data["name"], scale_raw) or extract_scale(category_raw)

    # Price (JPY)
    price_raw = specs.get("price") or specs.get("msrp") or specs.get("retail price") or ""
    data["price_jpy"] = clean_price(price_raw)

    # Dimensions / material (nice to have)
    data["dimensions"] = specs.get("dimensions") or specs.get("size")
    data["material"]   = specs.get("material") or specs.get("materials")
    data["barcode"]    = specs.get("jan") or specs.get("barcode") or specs.get("jan code")

    # Description / notes
    desc_el = soup.select_one(".product-description, .item-description, .description, .item-note")
    data["description"] = desc_el.get_text(strip=True)[:400] if desc_el else ""

    # MFC user stats (nice extra data)
    owned_el = soup.select_one(".nb-users-owned, [class*='owned']")
    data["mfc_owned_count"] = int(re.sub(r"\D", "", owned_el.get_text())) if owned_el and owned_el.get_text().strip() else None

    # Normalise type
    data["type"] = normalize_type(data["name"], category_raw)

    # Events / series tags
    data["events"]      = extract_events(data["name"])
    data["illustrator"] = extract_illustrator(data["name"], data.get("description", ""))

    # Build unified tags list
    tags = [data["type"]]
    tags.extend(data["events"])
    if data["illustrator"]:
        tags.append(data["illustrator"])
    if data.get("manufacturer"):
        tags.append(data["manufacturer"])
    if data.get("release_date"):
        yr = int(data["release_date"][:4])
        if yr <= 2012: tags.append("Early Era (2007–2012)")
        elif yr <= 2016: tags.append("Mid Era (2013–2016)")
        elif yr <= 2020: tags.append("Modern Era (2017–2020)")
        else: tags.append("Recent (2021+)")
    data["tags"] = sorted(set(tags))

    # Canonical release year (integer, for easy sorting)
    data["year"] = int(data["release_date"][:4]) if data.get("release_date") else None

    return data


# ──────────────────────────────────────────────
# MERGE / DEDUPLICATE
# ──────────────────────────────────────────────

def load_existing() -> dict[str, dict]:
    if FIGURES_FILE.exists():
        try:
            with open(FIGURES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {fig["id"]: fig for fig in data if fig.get("id")}
        except Exception as e:
            log.warning(f"Could not load existing figures.json: {e}")
    return {}


def save_figures(figures: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Sort by release date descending, then name
    figures.sort(
        key=lambda f: (f.get("release_date") or "0000-00", f.get("name", "")),
        reverse=True,
    )
    with open(FIGURES_FILE, "w", encoding="utf-8") as f:
        json.dump(figures, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(figures)} figures → {FIGURES_FILE}")


def save_meta(stats: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stats["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    log.info(f"Saved meta → {META_FILE}")


# ──────────────────────────────────────────────
# MAIN SCRAPE LOOP
# ──────────────────────────────────────────────

def scrape(incremental: bool = False, page_limit: int | None = None) -> None:
    existing = load_existing()
    log.info(f"Loaded {len(existing)} existing figures.")

    # ── 1. Discover total count & first stubs ──
    first_url = build_browse_url(offset=0)
    log.info(f"Fetching browse page 1: {first_url}")
    soup = get_page(first_url)
    if not soup:
        log.error("Could not fetch first page. Aborting.")
        sys.exit(1)

    stubs, total = parse_browse_page(soup)

    # Estimate total pages
    total_pages = max(1, -(-total // PAGE_SIZE))  # ceiling division
    if page_limit:
        total_pages = min(total_pages, page_limit)

    log.info(f"Total figures on MFC: {total} → {total_pages} pages to scrape")

    # ── 2. Collect all stubs from listing pages ──
    all_stubs = list(stubs)
    for page_num in range(1, total_pages):
        offset = page_num * PAGE_SIZE
        url = build_browse_url(offset=offset)
        log.info(f"Fetching page {page_num + 1}/{total_pages} (offset={offset})")
        page_soup = get_page(url)
        if page_soup:
            page_stubs, _ = parse_browse_page(page_soup)
            all_stubs.extend(page_stubs)
        time.sleep(DELAY_BETWEEN_PAGES)

    log.info(f"Collected {len(all_stubs)} figure stubs total.")

    # ── 3. Fetch detail pages for new/unknown figures ──
    new_count  = 0
    skip_count = 0
    figures    = dict(existing)  # id → figure dict

    for i, stub in enumerate(all_stubs):
        fig_id = stub.get("id")
        if not fig_id:
            continue

        if incremental and fig_id in figures:
            skip_count += 1
            continue

        log.info(f"[{i+1}/{len(all_stubs)}] Fetching detail: {stub['name'][:60]}")
        detail_soup = get_page(stub["detail_url"])
        if detail_soup:
            enriched = parse_detail_page(detail_soup, stub)
            figures[fig_id] = enriched
            new_count += 1
        else:
            # Keep stub data if detail fetch fails
            stub["type"]       = normalize_type(stub["name"])
            stub["events"]     = extract_events(stub["name"])
            stub["tags"]       = [stub["type"]] + stub["events"]
            stub["year"]       = int(stub["release_date"][:4]) if stub.get("release_date") else None
            stub["illustrator"] = None
            figures[fig_id] = stub

        time.sleep(DELAY_BETWEEN_ITEMS)

    log.info(f"Done. New/updated: {new_count} | Skipped (cached): {skip_count}")

    # ── 4. Save ──
    final_list = list(figures.values())
    save_figures(final_list)

    # Build stats
    by_type = {}
    by_year = {}
    by_event = {}
    for f in final_list:
        t = f.get("type", "Other")
        by_type[t] = by_type.get(t, 0) + 1
        y = str(f.get("year", "Unknown"))
        by_year[y] = by_year.get(y, 0) + 1
        for ev in f.get("events", []):
            by_event[ev] = by_event.get(ev, 0) + 1

    save_meta({
        "total_figures":  len(final_list),
        "new_this_run":   new_count,
        "by_type":        dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "by_year":        dict(sorted(by_year.items())),
        "by_event":       dict(sorted(by_event.items(), key=lambda x: -x[1])),
        "scrape_mode":    "incremental" if incremental else "full",
    })


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MFC → Hatsune Miku Figure Scraper")
    parser.add_argument("--incremental", action="store_true",
                        help="Skip figures already in figures.json (faster daily runs)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max pages to scrape (for testing)")
    args = parser.parse_args()

    log.info("══════════════════════════════════════")
    log.info("  Hatsune Miku Figure Archive Scraper ")
    log.info(f"  Mode: {'incremental' if args.incremental else 'full'}")
    log.info(f"  Target char ID: {MFC_CHAR_ID} (Hatsune Miku)")
    log.info("══════════════════════════════════════")

    scrape(incremental=args.incremental, page_limit=args.limit)
