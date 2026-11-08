"""Offline checks for the tagging and Latendo matching/parsing rules.

Run from the scraper folder:  python -m unittest test_scrapers
"""

import unittest

import hlj_scraper as h
import latendo_scraper as L


def key(name, scale=None, typ=None):
    return L.match_key({"name": name, "scale": scale, "type": typ or h.classify(name, None)})


class Tagging(unittest.TestCase):
    def test_illustrator_word_bounded(self):
        self.assertIsNone(h.extract_illustrator("Hatsune Miku Wonderland Figure Cinderella"))
        self.assertIsNone(h.extract_illustrator("Nendoroid Hatsune Miku: Cantarella Ver."))
        self.assertEqual(h.extract_illustrator("Hatsune Miku Luminasta 16th Anniversary KEI Ver."), "KEI")
        self.assertEqual(h.extract_illustrator("1/4 PRISMA WING Hatsune Miku Art by neco Statue"), "neco")

    def test_events(self):
        self.assertIn("Sakura Miku", h.extract_events("POP UP PARADE Sakura Miku: Hanami Outfit Ver."))
        self.assertIn("Project SEKAI", h.extract_events("Nendoroid Hatsune Miku (Colorful Stage! The Movie)"))

    def test_retag_dedupes_tags(self):
        row = {"name": "Snow Miku 2024 Nendoroid", "type": "Nendoroid",
               "manufacturer": "Good Smile Company", "series": None,
               "tags": ["Nendoroid", "Snow Miku", "Snow Miku", "Good Smile Company"]}
        h.retag(row)
        self.assertEqual(row["tags"], ["Nendoroid", "Snow Miku", "Good Smile Company"])


class Matching(unittest.TestCase):
    def same(self, a, b):
        return L.same_figure(a, b)

    def test_same_product_across_retailers(self):
        self.assertTrue(self.same(key("Character Vocal Series 01 Hatsune Miku feat. Yoneyama Mai"),
                                  key("1/7 Hatsune Miku feat. Yoneyama Mai (Character Vocal Series 01: Hatsune Miku)", "1/7")))
        self.assertTrue(self.same(key("Nendoroid 1309 Character Vocal Series 01 Hatsune Miku V4X (Re-issue)"),
                                  key("Nendoroid Hatsune Miku V4X (Rerelease)")))
        self.assertTrue(self.same(key("Hatsune Miku GT Project Racing Miku 2025Ver."),
                                  key("1/7 Hatsune Miku GT Project: Racing Miku 2025 Ver.", "1/7")))

    def test_variants_and_series_differ(self):
        self.assertFalse(self.same(key("MC-06 Hatsune Miku x Cinnamoroll Potekoro Mascot (M Size) A Hatsune Miku"),
                                   key("Hatsune Miku x Cinnamoroll: MC-06 Potekoro Mascot Msize B: Hatsune Miku")))
        self.assertFalse(self.same(key("Blind Box Racing Miku All Stars Figure Collection Vol. 2"),
                                   key("Hatsune Miku Blind Box Series: Snow Miku All Stars Figure Collection Vol. 2")))
        self.assertFalse(self.same(key("Racing Miku 2023 Ver."), key("Racing Miku 2024 Ver.")))

    def test_product_lines_differ(self):
        self.assertFalse(self.same(key("Character Vocal Series 01 Hatsune Miku Happy 16th Birthday Ver.", typ="Other"),
                                   key("Nendoroid Hatsune Miku: Happy 16th Birthday Ver. (Rerelease)")))


PAGE = """
<meta property="og:title" content="(PO) Character Vocal Series 01 Hatsune Miku: Music &amp; Fire Works Ver."/>
<meta property="og:image" content="https://www.latendo.com/web/image/product.template/454351/image_1024"/>
<p class="mb-1">Series: <span>Hatsune Miku</span></p>
<p class="mb-1">Brand: <span>Good Smile Company</span></p>
<p class="mb-1">Category: <span>Complete Figure</span></p>
<p class="mb-1">Size: <span>1/7 (230mm)</span></p>
<p class="mb-1">Release Date: <span>2027-09-30</span></p>
<span itemprop="price" style="display:none;">273.6</span>
<span itemprop="priceCurrency" style="display:none;">SGD</span>
"""


class LatendoPage(unittest.TestCase):
    def test_parse_figure(self):
        row = L.parse_product(PAGE, "po-character-vocal-series-01-hatsune-miku-music-fire-works-ver-454351")
        self.assertEqual(row["id"], "LT454351")
        self.assertEqual(row["name"], "Character Vocal Series 01 Hatsune Miku: Music & Fire Works Ver.")
        self.assertEqual((row["type"], row["scale"], row["dimensions"]), ("Scale", "1/7", "230mm"))
        self.assertEqual((row["release_date"], row["year"], row["price_sgd"]), ("2027-09", 2027, 273.6))

    def test_goods_and_other_franchises_skipped(self):
        self.assertIsNone(L.parse_product(PAGE.replace("Complete Figure", "Accessories"), "x-miku-1"))
        other = PAGE.replace("Series: <span>Hatsune Miku", "Series: <span>The Idolmaster") \
                    .replace("Character Vocal Series 01 Hatsune Miku", "Miku Maekawa")
        self.assertIsNone(L.parse_product(other, "x-miku-1"))

    def test_slug_prefilter(self):
        self.assertIsNone(h.classify(L.slug_name("po-hatsune-miku-plushie-reusable-bag-182204"), None))
        self.assertIsNotNone(h.classify(L.slug_name("nendoroid-1777-hatsune-miku-maneki-miku-ver-346915"), None))


if __name__ == "__main__":
    unittest.main()
