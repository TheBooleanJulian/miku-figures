#!/usr/bin/env python3
"""
MyFigureList scraper — adds Hatsune Miku figures from myfigurelist.com (database, JPY).
======================================================================================
MyFigureList is a figure database and price-comparison site (~125k figures). Its
robots.txt allows crawling everything except editors, admin and /api/offer/
(affiliate redirects, never fetched here), and its llms.txt asks crawlers to use the
sitemaps and each page's JSON-LD. This scraper reads the three figure sitemaps,
keeps URLs whose slug names Miku and passes the classifier, then fetches those
figure pages slowly. A page is kept only when its breadcrumb character is Hatsune
Miku (or a Snow/Racing/Sakura Miku variant) and the classifier accepts its name.
robots.txt is checked every run, so a rule the site adds later is obeyed. Standard
library only; reuses the HLJ scraper's classifier and storage and the Nin-Nin-Game
scraper's robots and duplicate checks.

Only facts are stored (name, maker, series, JAN, price, date, scale, size, image
link), and every row links back to its MyFigureList page. The site's description
text is not copied.

Usage:
    python mfl_scraper.py            # fetch up to MAX_NEW new figure pages
    python mfl_scraper.py --max 10   # fetch at most 10 (dev/test)

Rows are written to ../public/figures.json with source="mfl". A figure whose JAN
another source already has is skipped; goods, other characters and duplicates are
remembered in mfl_skip.json.
"""

import argparse
import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import hlj_scraper as h
import latendo_scraper as L
import ninnin_scraper as N
from hlj_scraper import log

BASE = "https://myfigurelist.com"
SITEMAP_INDEX = BASE + "/sitemap.xml"
FIGURE_URL = BASE + "/figure/{pid}/{slug}"
MAX_NEW = 400                    # figure pages fetched per run; ~1,900 candidates clear over a few runs
DELAY = 2.0                      # seconds between requests (no crawl-delay is set; pages answer in ~0.3 s)
MAX_FAILURES = 8                 # consecutive failures before ending the run
SKIP_FILE = Path(__file__).parent / "mfl_skip.json"       # figure ids known to be goods/others/duplicates

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; miku-figures-archive; "
                  "+https://github.com/TheBooleanJulian/miku-figures)",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}

FIGURE_SITEMAP_RE = re.compile(r"<loc>(https://myfigurelist\.com/sitemaps/figure-\d+\.xml)</loc>")
FIGURE_URL_RE = re.compile(r"<loc>https://myfigurelist\.com/figure/(\d+)/([^<\s]+)</loc>")
LD_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
OG_IMAGE_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"')
# Breadcrumb characters that are Hatsune Miku
HATSUNE_CHAR_RE = re.compile(
    r"^(?:miku hatsune|hatsune miku)$|\b(?:snow|yuki|racing|sakura|hachune|append)\s*miku\b|"
    r"^miku\s*dayo", re.I)
SCALE_VALUE_RE = re.compile(r"^1/\d+$")
# Another character dressed as Miku: "Hatsune Miku Costume ver", "... - Hatsune Miku Ver."
COSTUME_RE = re.compile(r"costume|cosplay|\bmiku ver\b", re.I)


class Stop(Exception):
    """Rate limited, disallowed or failing repeatedly: end the run and keep progress."""


_failures = 0
_rules: list[tuple[bool, str]] = []


def fetch(url: str) -> str | None:
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
        log.warning(f"HTTP {e.code} for {url}")
        if e.code in (403, 429):
            raise Stop(f"HTTP {e.code} from myfigurelist.com at {url}")
    except Exception as e:
        log.warning(f"{type(e).__name__} for {url}: {e}")
    _failures += 1
    if _failures >= MAX_FAILURES:
        raise Stop(f"{_failures} consecutive failures, last: {url}")
    return None


def load_robots() -> None:
    """The site publishes a robots.txt; failing to read it stops the run."""
    global _rules
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + "/robots.txt", headers=HEADERS),
                                    timeout=30) as r:
            data = r.read()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        _rules = N.robots_rules(data.decode("utf-8", "replace"))
    except Exception as e:
        raise Stop(f"could not read robots.txt: {e}")


def slug_name(slug: str) -> str:
    return re.sub(r"\s+", " ", slug.replace("-", " ")).strip()


def wanted(slug: str) -> bool:
    """Pre-filter from the URL alone, before any figure page is fetched."""
    name = slug_name(slug)
    return bool(h.MIKU_RE.search(name)) and not L.KIT_RE.search(name) \
        and h.classify(name, None) is not None


def sitemap_figures() -> list[tuple[str, str]]:
    """(figure id, slug) of every figure in the sitemaps whose slug passes `wanted`."""
    index = fetch(SITEMAP_INDEX)
    if index is None:
        raise Stop("could not read the sitemap index")
    found: dict[str, str] = {}
    total = 0
    for url in FIGURE_SITEMAP_RE.findall(index):
        time.sleep(DELAY)
        body = fetch(url)
        if body is None:
            raise Stop(f"could not read {url}")       # a partial list would look like a smaller catalogue
        pairs = FIGURE_URL_RE.findall(body)
        total += len(pairs)
        found.update((pid, slug) for pid, slug in pairs if wanted(slug))
    log.info(f"Sitemaps: {total} figures, {len(found)} Miku candidates.")
    return sorted(found.items(), key=lambda p: int(p[0]))


# ──────────────────────────────────────────────
# FIGURE PAGE
# ──────────────────────────────────────────────

def _ld_blocks(page: str) -> tuple[dict, list[tuple[str, str]]]:
    """The Product block (may be empty) and the breadcrumb (name, url) pairs."""
    product: dict = {}
    crumbs: list[tuple[str, str]] = []
    for block in LD_RE.findall(page):
        try:
            ld = json.loads(block)
        except ValueError:
            continue
        if not isinstance(ld, dict):
            continue
        if ld.get("@type") == "Product":
            product = ld
        elif ld.get("@type") == "BreadcrumbList":
            crumbs = [(str(i.get("name") or ""), str(i.get("item") or ""))
                      for i in ld.get("itemListElement") or [] if isinstance(i, dict)]
    return product, crumbs


def _price(offers) -> int | None:
    """Lowest in-stock shop price (the aggregate's lowPrice), else the single listed price."""
    if not isinstance(offers, dict):
        return None
    value = offers.get("lowPrice") if offers.get("@type") == "AggregateOffer" else offers.get("price")
    if offers.get("priceCurrency", "JPY") != "JPY":
        return None
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def parse_product(page: str, pid: str) -> dict | None:
    """Row for a figure page, or None when it is not a Hatsune Miku figure.

    About one page in five has no Product block (no price, review or rating); its
    name and maker then come from the title, "<name> – <maker> | MyFigureList".
    """
    product, crumbs = _ld_blocks(page)
    # Home > series > character > figure; some figures have no character crumb
    middle = crumbs[1:-1]
    series = next((n for n, u in middle if "/series/" in u), None)
    character = next((n for n, u in middle if "/character/" in u), None)
    title = html.unescape(TITLE_RE.search(page).group(1)) if TITLE_RE.search(page) else ""
    title = re.sub(r"\s*\|\s*MyFigureList\s*$", "", title).strip()
    title_name, sep, title_maker = title.rpartition(" – ")
    if not sep:                                      # no maker in the title
        title_name, title_maker = title, ""
    name = html.unescape(str(product.get("name") or title_name or title))
    name = re.sub(r"\s+", " ", name).strip()
    brand = product.get("brand")
    maker = (brand.get("name") if isinstance(brand, dict) else brand) or title_maker or None
    maker = maker.strip() if isinstance(maker, str) and maker.strip() else None
    if not name or L.KIT_RE.search(name):
        return None
    # The breadcrumb names one character and is sometimes wrong (a Racing Miku set
    # filed under Rin Kagamine) or the collab partner ("Snow Miku x Kuromi" under
    # Kuromi). So a non-Miku character only rejects a name that doesn't name Miku,
    # or one where that character wears Miku's outfit ("Sonico - Hatsune Miku Costume ver").
    if character and not HATSUNE_CHAR_RE.search(character) \
            and (not h.VOCALOID_NAME_RE.search(name) or COSTUME_RE.search(name)):
        return None
    typ = h.classify(name, maker)
    if typ is None:
        return None

    props = {str(p.get("name")): str(p.get("value"))
             for p in product.get("additionalProperty") or [] if isinstance(p, dict)}
    scale = props.get("Scale") if SCALE_VALUE_RE.match(props.get("Scale", "")) else None
    category = str(product.get("category") or "") or None
    if typ == "Other":
        low_cat = (category or "").lower()
        if "plush" in low_cat:
            typ = "Plush / Soft"
        elif "doll" in low_cat:
            typ = "Doll / BJD"
        elif "garage" in low_cat:
            typ = "Garage Kit"
        elif scale:
            typ = "Scale"

    release = None
    if rd := re.match(r"(\d{4})-(\d{2})", str(product.get("releaseDate") or "")):
        release = f"{rd.group(1)}-{rd.group(2)}"

    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if not image and (og := OG_IMAGE_RE.search(page)):
        image = html.unescape(og.group(1))

    height = product.get("height")
    dimensions = None
    if isinstance(height, dict) and isinstance(height.get("value"), (int, float)) and height["value"] > 0:
        dimensions = f"{height['value']:g}cm" if height.get("unitCode", "CMT") == "CMT" else None
    material = product.get("material")
    if isinstance(material, list):
        material = ", ".join(str(m) for m in material) or None

    jan = str(product.get("gtin13") or "").strip()
    jan = jan if re.fullmatch(r"\d{8,14}", jan) else None
    url = str(product.get("url") or "") or FIGURE_URL.format(pid=pid, slug="")

    return {
        "id": "MF" + pid,
        "name": name,
        "manufacturer": maker,
        "release_date": release,
        "year": int(release[:4]) if release else None,
        "type": typ,
        "scale": scale,
        "price_jpy": _price(product.get("offers")),
        "price_sgd": None,
        "price_usd": None,
        "image_url": image or None,
        "detail_url": url,
        "events": [],                                # filled by h.retag()
        "illustrator": None,
        "tags": [],
        "description": "",                           # not copied: the site's own text
        "dimensions": dimensions,
        "material": material or None,
        "barcode": jan,
        "mfc_owned_count": None,
        "series": series,
        "category": category,
        "item_type": None,
        "source": "mfl",
        "handle": pid,
    }


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

class OtherRows(N.Others):
    """Other sources' rows; also counts every Good Smile variant JAN (rereleases)."""

    def __init__(self, rows: list[dict]):
        super().__init__(rows)
        for f in rows:
            self.codes.update(j for j in f.get("jans") or [] if j)


def duplicate(row: dict, others: N.Others) -> bool:
    return others.has(row)


def main(max_new: int, verbose: bool = False) -> int:
    saved = json.loads(h.FIGURES_FILE.read_text(encoding="utf-8")) if h.FIGURES_FILE.exists() else []
    others_rows = [f for f in saved if f.get("source") != "mfl"]
    others = OtherRows(others_rows)
    skip = set(json.loads(SKIP_FILE.read_text())) if SKIP_FILE.exists() else set()

    # Re-judge saved rows: another source picking a figure up keeps theirs
    mine: dict[str, dict] = {}
    for f in (f for f in saved if f.get("source") == "mfl"):
        if duplicate(f, others):
            log.info(f"Dropping saved row: {f['name'][:60]}")
            skip.add(f["id"])
        else:
            mine[f["id"]] = f
    log.info(f"Loaded {len(mine)} MyFigureList rows, {len(others_rows)} from other sources, {len(skip)} skipped ids.")

    new = not_figure = dupes = 0
    try:
        load_robots()
        figures = sitemap_figures()
        todo = [(pid, slug) for pid, slug in figures if "MF" + pid not in mine and "MF" + pid not in skip]
        log.info(f"{len(todo)} to fetch (cap {max_new}).")
        for i, (pid, slug) in enumerate(todo[:max_new], 1):
            time.sleep(DELAY)
            page = fetch(FIGURE_URL.format(pid=pid, slug=slug))
            if page is None:
                continue
            row = parse_product(page, pid)
            reason = "not a Miku figure" if row is None else \
                "duplicate" if duplicate(row, others) or N.own_match(row, mine) else None
            if reason:
                not_figure += reason != "duplicate"
                dupes += reason == "duplicate"
                if verbose:
                    log.info(f"Skip MF{pid} ({reason}): {slug_name(slug)[:70]}")
                skip.add("MF" + pid)
                continue
            mine[row["id"]] = row
            new += 1
            if i % 25 == 0:
                log.info(f"[{i}/{min(len(todo), max_new)}] {row['name'][:60]}")
    except Stop as e:
        log.warning(f"Ending the run early and keeping progress ({e}).")

    SKIP_FILE.write_text(json.dumps(sorted(skip)))
    log.info(f"Done. New: {new} | Not Miku figures: {not_figure} | Duplicates: {dupes} | MyFigureList rows: {len(mine)}")
    h.write_outputs(others_rows + list(mine.values()), new, "mfl")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="MyFigureList -> Hatsune Miku Figure Scraper")
    ap.add_argument("--max", type=int, default=MAX_NEW, help="Max figure pages to fetch")
    ap.add_argument("--verbose", action="store_true", help="Log each skipped figure and why")
    args = ap.parse_args()
    sys.exit(main(args.max, args.verbose))
