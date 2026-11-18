"""Offline checks for the tagging, Latendo matching/parsing and Nin-Nin-Game rules.

Run from the scraper folder:  python -m unittest test_scrapers
"""

import unittest

import hlj_scraper as h
import latendo_scraper as L
import ninnin_scraper as N


def key(name, scale=None, typ=None):
    return L.match_key({"name": name, "scale": scale, "type": typ or h.classify(name, None)})


class Classifier(unittest.TestCase):
    NOT_MIKU = [
        "Hatsune Miku Series: Kagamine Rin Fuwapuchi Dodeka Jumbo Plush Toy",
        "Hatsune Miku Series Chibigurumi D: Luka",
        "1/7 Hatsune Miku -Project DIVA- F 2nd: Megurine Luka: Temptation Ver. PVC",
        "1/7 Hatsune Miku -Project DIVA- F 2nd: Kagamine Len Stylish Energy L Ver. PVC",
        "1/6 Hatsune Miku GT Project: Super Sonico Racing Ver. 2016 PVC",
        "Kagamine Len HappyKuji HappyKuji Hatsune Miku 2013 Summer ver. Nendoroid #341",
        "Asahina Mikuru 1/4 Bunny Ver.",
        "Shiino Mikuro 1/6 Nurse Ver.",
        "Love Live SNOW MIKU 2016 Stuffed Rin Hoshizora",
        "Nendoroid 2911 Hatsune Miku: Colorful Stage! Kohane Azusawa",
        "POP UP PARADE Kanade Yoisaki (HATSUNE MIKU: COLORFUL STAGE!)",
        "Hatsune Miku - Kaito Mochipiko Plush (3 designs available)",
        "Hatsune Miku BiCute Bunnies Figure Megurin Luka",
        "Hatsune Miku Face Hugging Pillow",
        "Hatsune Miku Relax Life Plush Eye Mask",
        "Hatsune Miku Squinty Eyes Plush Card Binder",
        "5th Hatsune Miku × GS Illustration Contest: KAITO (Chinese Style Ver.) - G.S.Collection (Limited + Bonus)",
        "Hatsune Miku: Sparkling Clear Card & Gum Vol.2 (18 Pack Box)",
        "Hatsune Miku GT Project 1/43: Good Smile Hatsune Miku AMG 2019 (Reissue)",
        "Vocaloid Hatsune Miku Itasha BMW Z4 2011 1/43 Racing 2011 Sepang Champion Ver.",
        "Hatsune Miku x Hokusai: Folding Fan - 36 Views of Mount Fuji Series (Fine Wind Clear Morning)",
        "Hatsune Miku x Koshu Inden: Kiss Lock Purse - Future",
        "The Broken SEKAI and the Miku Who Can't Sing: Lying Down Plush - Mafuyu Asahina",
        "Look Up: Hatsune Miku - Megurine Luka & KAITO (Limited + Bonus)",
        "Hatsune Miku: KAITO - Snow Miku 2026 Ver. Snowman Plush Mascot",
    ]
    MIKU = [
        "Piapro Characters Trading Minifigure Series MEIKO & Miku Hatsune",
        "Love Live SNOW MIKU 2016 Stuffed SNOW MIKU 2016",
        "1/7 HATSUNE MIKU: COLORFUL STAGE! Hatsune Miku: Rose Cage Ver.",
        "Nendoroid 2089 Project SEKAI Colorful Stage! feat. Hatsune Miku Hatsune Miku: Street SEKAI Ver.",
        "Nendoroid 2904 Colorful Stage! The Movie: A Miku Who Can't Sing Hatsune Miku: Unshuttered Sekai Ver.",
        "1/7 Hatsune Miku GT Project: Racing Miku 2025 Ver.",
        "Nendoroid Mikudayo",
        "Hatsune Miku Play Plush Hatsune Miku",
        "Hatsune Miku MIKU WITH YOU 2018 Ver.",
        "Hatsune Miku x Cinnamoroll Chibi Figure",
        "MC-22 Hatsune Miku x Cinnamoroll: Fluffy M Size 3E Hatsune Miku (Scarf)",
        "Hatsune Miku Sweet Intertwining Magnetic Lay Down Plush Hatsune Miku",
        "The Broken SEKAI and the Miku Who Can't Sing: Lying Down Plush - Hatsune Miku in a World with No One",
        "Look Up: Hatsune Miku - Hatsune Miku & MEIKO (Limited + Bonus)",
        "Nendoroid 3145: Hatsune Miku - Katsushika Hokusai Collaboration Ver.",
        "Snow Miku: Fuwa Kororin M Size G - Snow Miku (2016 Ver.)",
    ]

    def test_other_characters_dropped(self):
        for name in self.NOT_MIKU:
            self.assertIsNone(h.classify(name, None), name)

    def test_miku_kept(self):
        for name in self.MIKU:
            self.assertIsNotNone(h.classify(name, None), name)


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

    def test_catalogue_number_and_form_decide(self):
        self.assertFalse(self.same(
            key("Nendoroid 2193 Project SEKAI Colorful Stage! feat. Hatsune Miku - Hatsune Miku School SEKAI Ver."),
            key("Nendoroid 2089 Project SEKAI Colorful Stage! feat. Hatsune Miku - Hatsune Miku Street SEKAI Ver.")))
        self.assertTrue(self.same(
            key("Nendoroid 2193 Project SEKAI Colorful Stage! feat. Hatsune Miku - Hatsune Miku School SEKAI Ver."),
            key("Hatsune Miku Nendoroid #2193 School SEKAI Ver.")))
        self.assertFalse(self.same(
            key("Nendoroid Doll SEGA feat. HATSUNE MIKU Project Hatsune Miku: Infinity Ver."),
            key("Nendoroid Doll Outfit Set SEGA feat. HATSUNE MIKU Project Hatsune Miku: Infinity Ver.")))

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


ROBOTS = """
User-agent: *
Content-Signal: ai-train=no, search=yes, ai-input=yes
Disallow: /*?p=
Disallow: /*manufacturers*
Disallow: /*search_query=
Disallow: /*n=
Disallow: /*controller=search
Allow: *.js*
Sitemap: https://www.nin-nin-game.com/1_index_sitemap.xml
"""

# Trimmed from real product pages (2026-11-17)
NG_PAGE = """
<script type="application/ld+json">
    {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": "Nendoroid 3145: Hatsune Miku - Katsushika Hokusai Collaboration Ver. [Good Smile Company]",
        "image": ["https://media1.nin-nin-game.com/838178-large_default/nendoroid-3145.jpg"],
        "sku": "4570232593367",
        "gtin13": "4570232593367",
        "brand": {"@type": "Brand", "name": "Good Smile Company"},
        "offers": {"@type": "Offer", "priceCurrency": "USD", "price": "48.24"}
    }
</script>
<div class="rte product-page-tab" id="idTab1"><div class="product-page-attributes"><div class="product-page-attributes-item"><span>Brand/Manufacturer:</span> <a href="#">Good Smile Company</a></div><div class="product-page-attributes-item feature-item"> <span class="feature-title">Series:</span> <a href="#">Hatsune Miku</a></div></div><p><span style="font-size: 10pt;"><strong>Japanese Original Edition,&nbsp;<strong><strong>Nendoroid Figure</strong></strong></strong></span></p><div class="b-text-group"><p><span dir="auto">From the "<strong>Katsushika Hokusai x Hatsune Miku</strong>" project comes a <strong>Nendoroid</strong> of <strong>Hatsune Miku</strong> featuring a collaboration design by illustrator Rella! Includes:</span></p><p>・Interchangeable face parts.<br />・Optional parts include a "brush" and more.</p></div><p><strong><span style="font-size: 10pt;"><span style="text-decoration-line: underline;">Details</span>:</span></strong></p><p><span style="font-size: 10pt;"><strong>Maker:&nbsp;</strong>Good Smile Company</span><br /><span style="font-size: 10pt;"><strong>Material:&nbsp;</strong>PVC, ABS</span><br /><span style="font-size: 10pt;"><strong>Size</strong>: ~ (H) 10.0 cm</span><br /><span style="font-size: 10pt;"><strong>Release Date:&nbsp;</strong>2027/04</span></p><div id="product_reference"> <strong>Reference: </strong> <span class="editable">4570232593367</span></div>
"""

NG_USED = """
<script type="application/ld+json">
 { "@context": "https://schema.org/", "@type": "Product", "name": "Premium Chokonose Figure - Hatsune Miku x Cinnamoroll (Osumashi Ver.) (2nd Hand) [SEGA]", "image": [ "https://media2.nin-nin-game.com/484793-large_default/x.jpg" ], "gtin13": "4582733434322", "brand": { "@type": "Brand", "name": "Sega" }, "offers": { "@type": "Offer", "priceCurrency": "USD", "price": "25.18" } }
</script>
<div class="rte product-page-tab" id="idTab1"><div class="product-page-attributes"><div class="product-page-attributes-item"><span>Brand/Manufacturer:</span> <a href="#">Sega</a></div><div class="product-page-attributes-item feature-item"> <span class="feature-title">Series:</span> <a href="#" style="margin-right: 6px;">Hatsune Miku</a> <a href="#">Vocaloid</a></div></div><p><span style="color: #000000; font-size: 10pt;"><strong>Japanese Original Edition, 2nd hand SEGA Prize Figure</strong></span></p><p>This delightful <strong>Chokonose figure</strong> features the beloved <strong>Hatsune Miku</strong> holding the adorable <strong>Cinnamoroll</strong> in her arms.</p><p><span style="text-decoration: underline; color: #000000; font-size: 10pt;"><strong>Details:</strong></span></p><p><span style="color: #000000; font-size: 10pt;"><strong>Maker:&nbsp;</strong>SEGA</span><br /><span style="color: #000000; font-size: 10pt;"><strong>Material:&nbsp;</strong>PVC / ABS</span><br /><span style="color: #000000; font-size: 10pt;"><strong>Size:&nbsp;</strong>~ 14 cm<strong><br /></strong><strong>Release Date:&nbsp;</strong>2024/11</span></p><div id="product_reference"> <strong>Reference: </strong> <span class="editable">4582733434322</span></div>
"""


class NinNinGame(unittest.TestCase):
    def test_robots_wildcards(self):
        rules = N.robots_rules(ROBOTS)
        base = "https://www.nin-nin-game.com"
        self.assertFalse(N.robots_allows(base + "/en/search?search_query=hatsune+miku", rules))
        self.assertFalse(N.robots_allows(base + "/en/nendoroid?p=2", rules))
        self.assertTrue(N.robots_allows(base + "/en/nendoroid/259088-nendoroid-3145-hatsune-miku-.html", rules))
        self.assertTrue(N.robots_allows(base + "/1_en_0_sitemap.xml", rules))

    def test_parse_new_figure(self):
        row = N.parse_product(NG_PAGE, "nendoroid", "259088", "nendoroid-3145-hatsune-miku")
        self.assertEqual(row["id"], "NG259088")
        self.assertEqual(row["name"], "Nendoroid 3145: Hatsune Miku - Katsushika Hokusai Collaboration Ver.")
        self.assertEqual((row["type"], row["manufacturer"], row["series"]),
                         ("Nendoroid", "Good Smile Company", "Hatsune Miku"))
        self.assertEqual((row["barcode"], row["price_usd"]), ("4570232593367", 48.24))
        self.assertEqual((row["release_date"], row["year"]), ("2027-04", 2027))
        self.assertEqual((row["dimensions"], row["material"]), ("(H) 10.0 cm", "PVC, ABS"))
        self.assertIn("Katsushika Hokusai", row["description"])
        self.assertNotIn("Japanese Original Edition", row["description"])
        self.assertFalse(N.is_used(row))

    def test_parse_second_hand_prize(self):
        row = N.parse_product(NG_USED, "hatsune-miku", "156114",
                              "premium-chokonose-figure-hatsune-miku-x-cinnamoroll-osumashi-ver-2nd-hand-sega-")
        self.assertEqual(row["name"], "Premium Chokonose Figure - Hatsune Miku x Cinnamoroll (Osumashi Ver.)")
        self.assertEqual((row["type"], row["release_date"], row["dimensions"]), ("Prize", "2024-11", "14 cm"))
        self.assertEqual(row["series"], "Hatsune Miku, Vocaloid")
        self.assertTrue(N.is_used(row))

    def test_other_franchise_skipped(self):
        other = NG_USED.replace('6px;">Hatsune Miku</a> <a href="#">Vocaloid', '6px;">The Quintessential Quintuplets') \
                       .replace("Hatsune Miku x Cinnamoroll", "Miku Nakano")
        self.assertIsNone(N.parse_product(other, "the-quintessential-quintuplets", "1", "miku-nakano"))

    def test_url_prefilter(self):
        self.assertFalse(N.wanted("acrylic-stands", "hatsune-miku-x-rascal-2026-hatsune-miku-acrylic-stand-caravan-"))
        self.assertFalse(N.wanted("hatsune-miku", "hatsune-miku-face-towel-racing-miku-2025-caravan-"))
        self.assertFalse(N.wanted("other-goods", "hatsune-miku-spring-miku-full-graphic-t-shirt-white-xl-goods-"))
        self.assertFalse(N.wanted("plamatea", "hatsune-miku-plamatea-plastic-model-good-smile-company-"))
        self.assertFalse(N.wanted("the-quintessential-quintuplets",
                                  "luminasta-the-quintessential-quintuplets-miku-nakano-2nd-hand-sega-"))
        self.assertTrue(N.wanted("nendoroid", "nendoroid-3145-hatsune-miku-katsushika-hokusai-collaboration-ver-good-smile-company-"))
        self.assertTrue(N.wanted("hatsune-miku", "vocaloid-series-hatsune-miku-miku-hatsune-mebae-ver-max-factory-en"))


if __name__ == "__main__":
    unittest.main()
