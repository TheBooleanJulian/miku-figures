#!/usr/bin/env python3
"""
Solaris Japan scraper — adds Hatsune Miku figures that HLJ doesn't carry.
==========================================================================
Solaris is a Shopify store whose agents.md allows read-only browsing of search
and product pages/JSON. It rate-limits per IP (HTTP 429), so this scraper is
slow on purpose, honours Retry-After, and ends the run early instead of
hammering. Standard library only; reuses the HLJ scraper's classifier/storage.

Usage:
    python solaris_scraper.py             # fetch up to MAX_NEW new products
    python solaris_scraper.py --limit 2   # first 2 search pages (dev/test)

Rows are written to ../public/figures.json with source="solaris". Products whose
JAN barcode already exists in another source's rows are skipped (HLJ wins).
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import hlj_scraper as h
from hlj_scraper import log

BASE = "https://solarisjapan.com"
SEARCH_URL = BASE + "/search?q=hatsune+miku&type=product&page={page}"
PRODUCT_JSON = BASE + "/products/{handle}.json"
MAX_PAGES = 45                   # search is capped at 1000 results (~42 pages)
MAX_NEW = 300                    # products fetched per run; the backlog clears over a few daily runs
DELAY = 3.5                      # seconds between requests
MAX_429 = 3                      # consecutive rate-limit hits before ending the run
SKIP_FILE = Path(__file__).parent / "solaris_skip.json"   # handles known to be goods/duplicates

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; miku-figures-archive; "
                  "+https://github.com/TheBooleanJulian/miku-figures)",
    "Accept-Language": "en-US,en;q=0.9",
}

HANDLE_RE = re.compile(r'href="/products/([^"?/]+)\?_pos=')
# Product types that are plainly not figures
NON_FIGURE_RE = re.compile(
    r"card|apparel|clothing|accessor|\bbag|game|console|book|\bcd\b|dvd|blu-?ray|music|"
    r"stationery|poster|jewel|watch", re.I)


class RateLimited(Exception):
    pass


_429s = 0


def fetch(url: str) -> str | None:
    """GET with 429 handling. None on any non-rate-limit failure."""
    global _429s
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                _429s = 0
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _429s += 1
                wait = min(int(e.headers.get("Retry-After") or 60), 300)
                log.warning(f"429 from Solaris ({_429s}/{MAX_429}); waiting {wait}s")
                if _429s >= MAX_429:
                    raise RateLimited(url)
                time.sleep(wait)
                continue
            log.warning(f"HTTP {e.code} for {url}")
            return None
        except Exception as e:
            log.warning(f"{type(e).__name__} for {url}: {e}")
            return None


def collect_handles(page_limit: int) -> list[str]:
    handles: list[str] = []
    for page in range(1, page_limit + 1):
        body = fetch(SEARCH_URL.format(page=page))
        if body is None:
            break
        found = [x for x in dict.fromkeys(HANDLE_RE.findall(body)) if x not in handles]
        log.info(f"Search page {page}: {len(found)} new handles")
        if not found:
            break
        handles += found
        time.sleep(DELAY)
    return handles


def to_row(p: dict) -> dict | None:
    title = p.get("title", "")
    vendor = p.get("vendor") or None
    ptype = p.get("product_type") or ""
    if NON_FIGURE_RE.search(ptype):
        return None
    # "Franchise - Character - [Scale -] Name (Maker)"  ->  "Character [Scale] Name"
    parts = [x.strip() for x in title.split(" - ")]
    name = " ".join(parts[1:] if len(parts) >= 3 else parts)
    if vendor:
        name = re.sub(rf"\s*\({re.escape(vendor)}\)\s*$", "", name)
    typ = h.classify(name, vendor)
    if typ is None:
        return None
    if "plush" in ptype.lower() and typ == "Other":
        typ = "Plush / Soft"

    variants = p.get("variants") or []
    new = next((v for v in variants if (v.get("option1") or "").lower() == "brand new"),
               variants[0] if variants else {})
    try:
        price = float(new.get("price"))
    except (TypeError, ValueError):
        price = None
    cur = new.get("price_currency") or "USD"
    scale_m = h.SCALE_RE.search(name)
    events = h.extract_events(name)
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p.get("body_html") or "")).strip()
    return {
        "id": f"SJ{p['id']}",
        "name": name,
        "manufacturer": vendor,
        "release_date": None,
        "year": None,
        "type": typ,
        "scale": f"1/{scale_m.group(1)}" if scale_m else None,
        "price_jpy": None,
        "price_sgd": price if cur == "SGD" else None,
        "price_usd": price if cur == "USD" else None,
        "image_url": (p.get("image") or {}).get("src"),
        "detail_url": f"{BASE}/products/{p['handle']}",
        "events": events,
        "illustrator": h.extract_illustrator(name),
        "tags": [t for t in [typ, *events, vendor] if t],
        "description": body[:600],
        "dimensions": None,
        "material": None,
        "barcode": (new.get("barcode") or "").strip() or None,
        "mfc_owned_count": None,
        "series": None,
        "category": None,
        "item_type": ptype or None,
        "source": "solaris",
        "handle": p["handle"],
    }


def main(page_limit: int) -> int:
    saved = json.loads(h.FIGURES_FILE.read_text(encoding="utf-8")) if h.FIGURES_FILE.exists() else []
    mine = {f["handle"]: f for f in saved if f.get("source") == "solaris" and f.get("handle")}
    others = [f for f in saved if f.get("source") != "solaris"]
    other_codes = {f["barcode"] for f in others if f.get("barcode")}
    skip = set(json.loads(SKIP_FILE.read_text())) if SKIP_FILE.exists() else set()
    log.info(f"Loaded {len(mine)} Solaris rows, {len(others)} from other sources, {len(skip)} skipped handles.")

    new = skipped = 0
    try:
        handles = collect_handles(page_limit)
        todo = [x for x in handles if x not in mine and x not in skip]
        log.info(f"{len(handles)} handles; {len(todo)} to fetch (cap {MAX_NEW}).")
        for i, handle in enumerate(todo[:MAX_NEW], 1):
            body = fetch(PRODUCT_JSON.format(handle=handle))
            time.sleep(DELAY)
            if body is None:
                continue
            try:
                row = to_row(json.loads(body)["product"])
            except (ValueError, KeyError):
                continue
            if row is None or (row["barcode"] and row["barcode"] in other_codes):
                skip.add(handle)                 # goods, or already carried by another source
                skipped += 1
                continue
            mine[handle] = row
            new += 1
            if i % 25 == 0:
                log.info(f"[{i}/{min(len(todo), MAX_NEW)}] {row['name'][:60]}")
    except RateLimited as e:
        log.warning(f"Rate limited; ending the run early and keeping progress ({e}).")

    SKIP_FILE.write_text(json.dumps(sorted(skip)))
    log.info(f"Done. New: {new} | Skipped (goods/duplicates): {skipped}")
    h.write_outputs(others + list(mine.values()), new, "solaris")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Solaris Japan -> Hatsune Miku Figure Scraper")
    ap.add_argument("--limit", type=int, default=MAX_PAGES, help="Max search pages (testing)")
    sys.exit(main(ap.parse_args().limit))
