#!/usr/bin/env python3
"""
Nin-Nin-Game scraper — adds Hatsune Miku figures from nin-nin-game.com (Japan, USD).
====================================================================================
Nin-Nin-Game is a PrestaShop store with a deep back catalogue, second-hand stock
included, so it fills in older and discontinued figures. Its robots.txt disallows
search and pagination (`/*search_query=`, `/*?p=`), so this scraper never browses
the shop: it reads the sitemap (allowed), keeps product URLs whose slug mentions
Miku, and fetches only those product pages, slowly. Every URL is checked against
the live robots.txt before it is fetched (with `*` wildcards, which Python's
urllib.robotparser ignores). Standard library only; reuses the HLJ scraper's
classifier, tagging and storage and the Latendo scraper's name matching.

Usage:
    python ninnin_scraper.py            # fetch up to MAX_NEW new product pages
    python ninnin_scraper.py --max 10   # fetch at most 10 (dev/test)

Rows are written to ../public/figures.json with source="ninnin". Product pages
carry the JAN barcode, so a product another source already has is skipped by
barcode (or by name when either side lacks one). Second-hand listings share the
new item's JAN; the new listing is kept. Goods and duplicates are remembered in
ninnin_skip.json.
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
from hlj_scraper import log

BASE = "https://www.nin-nin-game.com"
ROBOTS_URL = BASE + "/robots.txt"
SITEMAP_INDEX = BASE + "/1_index_sitemap.xml"
MAX_NEW = 300                    # product pages fetched per run; the backlog clears over a few daily runs
DELAY = 3.0                      # seconds between requests
MAX_FAILURES = 8                 # consecutive failures before ending the run
SKIP_FILE = Path(__file__).parent / "ninnin_skip.json"    # product ids known to be goods/duplicates

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; miku-figures-archive; "
                  "+https://github.com/TheBooleanJulian/miku-figures)",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",   # the English sitemaps are ~80 MB raw, ~10 MB gzipped
}

SUB_SITEMAP_RE = re.compile(r"https://www\.nin-nin-game\.com/1_en_\d+_sitemap\.xml")
PRODUCT_URL_RE = re.compile(r"https://www\.nin-nin-game\.com/en/([a-z0-9-]+)/(\d+)-([a-z0-9-]*)\.html")
# Category slugs (first path part) that are plainly not figures. "hatsune-miku",
# "nendoroid", "*-prize", "other-plush", ... pass; the name classifier judges the rest.
NON_FIGURE_CAT_RE = re.compile(
    r"apparel|fashion|footwear|bags|pouches|watches|headphones|smartphone|stationery|"
    r"book|music|ost|softs|games|playstation|psvita|psp|nintendo|saturn|kitchen|house-decor|"
    r"candy|tcg|cards|weiss|acrylic|keychain|badges|tapestr|dakimakura|other-goods|"
    r"trading-goods|plamatea|moderoid|modeling-tools|frame-arms|gundam|hasegawa|plus18|binding")
USED_RE = re.compile(r"2nd-hand|second-hand|(?:^|-)used(?:-|$)|damaged", re.I)
# "(2nd Hand)", "(Used)", "(Damaged Box)", "(Brand New)" condition notes in titles
CONDITION_RE = re.compile(r"\s*[(\[]\s*(?:2nd hand|second hand|used[^)\]]*|damaged[^)\]]*|"
                          r"brand new|pre-owned)\s*[)\]]", re.I)
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


class Stop(Exception):
    """Rate limited, disallowed or failing repeatedly: end the run and keep progress."""


# ──────────────────────────────────────────────
# ROBOTS.TXT (with the * and $ wildcards robotparser ignores)
# ──────────────────────────────────────────────

def robots_rules(txt: str) -> list[tuple[bool, str]]:
    """(allow?, pattern) rules of the `User-agent: *` group(s)."""
    rules: list[tuple[bool, str]] = []
    active = in_rules = False
    for line in txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:                         # a User-agent after rules starts a new group
                active = in_rules = False
            active = active or val == "*"
        elif key in ("allow", "disallow"):
            in_rules = True
            if active and val:
                rules.append((key == "allow", val))
    return rules


def robots_allows(url: str, rules: list[tuple[bool, str]]) -> bool:
    """Longest matching rule wins; Allow wins a tie (Google's / RFC 9309 semantics)."""
    p = urllib.parse.urlsplit(url)
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    best_len, allow = -1, True
    for is_allow, pat in rules:
        rx = re.escape(pat).replace(r"\*", ".*")
        if rx.endswith(r"\$"):
            rx = rx[:-2] + "$"
        if re.match(rx, path) and (len(pat) > best_len or (len(pat) == best_len and is_allow)):
            best_len, allow = len(pat), is_allow
    return allow


# ──────────────────────────────────────────────
# HTTP
# ──────────────────────────────────────────────

_failures = 0
_rules: list[tuple[bool, str]] | None = None


def fetch(url: str) -> str | None:
    global _failures
    if _rules is not None and not robots_allows(url, _rules):
        raise Stop(f"robots.txt disallows {url}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
            data = r.read()
        _failures = 0
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        log.warning(f"HTTP {e.code} for {url}")
        if e.code in (403, 429):
            raise Stop(f"HTTP {e.code} from Nin-Nin-Game at {url}")
    except Exception as e:
        log.warning(f"{type(e).__name__} for {url}: {e}")
    _failures += 1
    if _failures >= MAX_FAILURES:
        raise Stop(f"{_failures} consecutive failures, last: {url}")
    return None


def load_robots() -> None:
    global _rules
    txt = fetch(ROBOTS_URL)
    if txt is None:
        raise Stop("could not read robots.txt")
    _rules = robots_rules(txt)


def sitemap_products() -> list[tuple[str, str, str]]:
    """(category slug, product id, slug) of every English product URL mentioning Miku."""
    index = fetch(SITEMAP_INDEX)
    if index is None:
        raise Stop("could not read the sitemap index")
    found: dict[str, tuple[str, str, str]] = {}
    for sub in dict.fromkeys(SUB_SITEMAP_RE.findall(index)):
        time.sleep(DELAY)
        body = fetch(sub)
        if body is None:
            continue
        for cat, pid, slug in PRODUCT_URL_RE.findall(body):
            if "miku" in slug:
                found[pid] = (cat, pid, slug)
    return list(found.values())


def slug_name(slug: str) -> str:
    return slug.replace("-", " ")


def wanted(cat: str, slug: str) -> bool:
    """Pre-filter from the URL alone, before any product page is fetched."""
    return not NON_FIGURE_CAT_RE.search(cat) and not L.KIT_RE.search(slug_name(slug)) \
        and h.classify(slug_name(slug), None) is not None


def is_used(f: dict) -> bool:
    return bool(USED_RE.search(f.get("handle") or ""))


# ──────────────────────────────────────────────
# PRODUCT PAGE
# ──────────────────────────────────────────────

def _product_ld(page: str) -> dict | None:
    for block in LD_RE.findall(page):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            return d
    return None


def _text_lines(fragment: str) -> list[str]:
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", fragment, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return [ln for ln in (re.sub(r"\s+", " ", x).strip() for x in s.split("\n")) if ln]


def parse_product(page: str, cat: str, pid: str, slug: str) -> dict | None:
    """Row for a product page, or None when it is not a Miku figure."""
    ld = _product_ld(page)
    if not ld or not ld.get("name"):
        return None
    title = html.unescape(ld["name"])
    brand = ((ld.get("brand") or {}).get("name") or "").strip() or None

    start = page.find('id="idTab1"')
    end = page.find('id="product_reference"', start)
    block = page[start:end] if start >= 0 else ""
    series_m = re.search(r'feature-title">\s*Series:\s*</span>(.*?)</div>', block, re.S)
    series = ", ".join(html.unescape(x).strip() for x in re.findall(r"<a[^>]*>([^<]+)</a>", series_m.group(1))) \
        if series_m else None
    series = series or None

    name = re.sub(r"\s*\[[^\]]*\]\s*$", "", title)          # trailing "[Good Smile Company]"
    name = CONDITION_RE.sub("", name).strip(" -")
    if L.KIT_RE.search(name):
        return None
    if series and not re.search(r"miku|vocaloid|project sekai|piapro", series, re.I) \
            and not h.VOCALOID_NAME_RE.search(name):
        return None                                          # another franchise's "Miku"
    typ = h.classify(name, brand)
    if typ is None:
        return None

    # Description, then a "Details:" list of "Maker: / Material: / Size: / Release Date:"
    body = block[block.find("<p", block.find("product-page-attributes")):] if block else ""
    lines = _text_lines(body)
    cut = next((i for i, ln in enumerate(lines) if re.fullmatch(r"Details\s*:?", ln, re.I)), len(lines))
    desc_lines, spec_lines = lines[:cut], lines[cut + 1:]
    lead = desc_lines[0] if desc_lines else ""
    if lead.lower().startswith("japanese original edition"):
        desc_lines = desc_lines[1:]                          # "Japanese Original Edition, Nendoroid Figure"
    specs = {}
    for ln in spec_lines:
        if m := re.match(r"([A-Za-z /]{2,20}?)\s*:\s*(.+)", ln):
            specs[m.group(1).strip().lower()] = m.group(2).strip()

    size = specs.get("size")
    scale_m = h.SCALE_RE.search(name) or h.SCALE_RE.search(size or "")
    low = f"{cat} {lead}".lower()
    if "plush" in low and typ in ("Other", "Prize"):
        typ = "Plush / Soft"
    elif typ == "Other":
        if re.search(r"prize|ufo-catcher", low):
            typ = "Prize"
        elif re.search(r"chibi-minifigures|shokugan|re-ment|trading figure|mini figure", low):
            typ = "Mini / Petite"
        elif scale_m:
            typ = "Scale"

    release = None
    if rm := re.search(r"(\d{4})\s*/\s*(\d{1,2})", specs.get("release date", "")):
        release = f"{rm.group(1)}-{int(rm.group(2)):02d}"

    offer = ld.get("offers") or {}
    price = None
    if offer.get("priceCurrency", "USD") == "USD":
        try:
            price = float(offer.get("price"))
        except (TypeError, ValueError):
            pass
    images = ld.get("image") or []
    image = images[0] if isinstance(images, list) and images else images or None
    desc, desc_size = h.clean_description("\n".join(desc_lines))
    barcode = str(ld.get("gtin13") or "").strip()

    return {
        "id": "NG" + pid,
        "name": name,
        "manufacturer": brand,
        "release_date": release,
        "year": int(release[:4]) if release else None,
        "type": typ,
        "scale": f"1/{scale_m.group(1)}" if scale_m else None,
        "price_jpy": None,
        "price_sgd": None,
        "price_usd": price,
        "image_url": image,
        "detail_url": f"{BASE}/en/{cat}/{pid}-{slug}.html",
        "events": [],                                        # filled by h.retag()
        "illustrator": None,
        "tags": [],
        "description": desc[:600],
        "dimensions": re.sub(r"^~\s*", "", size) if size else desc_size,
        "material": specs.get("material"),
        "barcode": barcode if re.fullmatch(r"\d{8,14}", barcode) else None,
        "mfc_owned_count": None,
        "series": series,
        "category": cat,
        "item_type": None,
        "source": "ninnin",
        "handle": f"{cat}/{pid}-{slug}",
    }


# ──────────────────────────────────────────────
# DUPLICATES
# ──────────────────────────────────────────────

class Others:
    """Rows of the other sources, indexed for duplicate checks."""

    def __init__(self, rows: list[dict]):
        self.codes = {f["barcode"] for f in rows if f.get("barcode")}
        self.keys = [L.match_key(f) for f in rows]
        self.keys_no_code = [L.match_key(f) for f in rows if not f.get("barcode")]

    def has(self, row: dict) -> bool:
        """Barcodes decide when both sides have one; otherwise fall back to names."""
        if row.get("barcode"):
            return row["barcode"] in self.codes or L.find_duplicate(row, self.keys_no_code)
        return L.find_duplicate(row, self.keys)


def own_match(row: dict, mine: dict[str, dict]) -> str | None:
    """Id of a saved Nin-Nin-Game row for the same product (same JAN, or same title)."""
    if row.get("barcode"):
        return next((k for k, f in mine.items() if f.get("barcode") == row["barcode"]), None)
    key = L.match_key(row)
    return next((k for k, f in mine.items() if L.same_figure(key, L.match_key(f), 1.0)), None)


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main(max_new: int) -> int:
    saved = json.loads(h.FIGURES_FILE.read_text(encoding="utf-8")) if h.FIGURES_FILE.exists() else []
    others_rows = [f for f in saved if f.get("source") != "ninnin"]
    others = Others(others_rows)
    skip = set(json.loads(SKIP_FILE.read_text())) if SKIP_FILE.exists() else set()

    # Re-judge saved rows: another source picking a figure up (keep theirs), or a
    # second listing of one we have (keep the new-condition one).
    mine: dict[str, dict] = {}
    for f in sorted((f for f in saved if f.get("source") == "ninnin"), key=is_used):
        if others.has(f) or own_match(f, mine):
            log.info(f"Dropping saved row: {f['name'][:60]}")
            skip.add(f["id"])
        else:
            mine[f["id"]] = f
    log.info(f"Loaded {len(mine)} Nin-Nin-Game rows, {len(others_rows)} from other sources, "
             f"{len(skip)} skipped ids.")

    new = skipped = 0
    try:
        load_robots()
        products = sitemap_products()
        todo = [p for p in products
                if "NG" + p[1] not in mine and "NG" + p[1] not in skip and wanted(p[0], p[2])]
        todo.sort(key=lambda p: (bool(USED_RE.search(f"{p[0]}/{p[2]}")), -int(p[1])))  # new stock first
        log.info(f"{len(products)} Miku product URLs; {len(todo)} to fetch (cap {max_new}).")
        for i, (cat, pid, slug) in enumerate(todo[:max_new], 1):
            time.sleep(DELAY)
            page = fetch(f"{BASE}/en/{cat}/{pid}-{slug}.html")
            if page is None:
                continue
            row = parse_product(page, cat, pid, slug)
            if row is not None and not others.has(row):
                dup = own_match(row, mine)
                if dup and is_used(mine[dup]) and not is_used(row):
                    skip.add(dup)                        # a new listing replaces a second-hand one
                    del mine[dup]
                    dup = None
                if dup is None:
                    mine[row["id"]] = row
                    new += 1
                    if i % 25 == 0:
                        log.info(f"[{i}/{min(len(todo), max_new)}] {row['name'][:60]}")
                    continue
            skip.add("NG" + pid)                         # goods, or already carried
            skipped += 1
    except Stop as e:
        log.warning(f"Ending the run early and keeping progress ({e}).")

    SKIP_FILE.write_text(json.dumps(sorted(skip)))
    log.info(f"Done. New: {new} | Skipped (goods/duplicates): {skipped} | Nin-Nin-Game rows: {len(mine)}")
    h.write_outputs(others_rows + list(mine.values()), new, "ninnin")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Nin-Nin-Game -> Hatsune Miku Figure Scraper")
    ap.add_argument("--max", type=int, default=MAX_NEW, help="Max product pages to fetch")
    sys.exit(main(ap.parse_args().max))
