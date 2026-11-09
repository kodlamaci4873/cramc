"""Tests for built-in and custom CRAMC appearance palettes."""
import unittest

from cramc_theme import THEME_IDS, normalize_color, palette_for


class ThemePaletteTests(unittest.TestCase):
    def test_all_builtin_palettes_are_complete(self):
        required = {"BG", "CARD", "CARD2", "CARD_BORDER", "FG", "FG_DIM",
                    "PANEL_BG", "PANEL_FG", "WARNING_BG", "WARNING_BORDER",
                    "NOTICE_BG", "MUTED_FG", "SUBTLE_FG"}
        for theme in THEME_IDS:
            if theme == "custom":
                continue
            with self.subTest(theme=theme):
                self.assertTrue(required.issubset(palette_for(theme)))

    def test_builtin_themes_are_distinct(self):
        backgrounds = {palette_for(theme)["BG"] for theme in THEME_IDS if theme != "custom"}
        self.assertEqual(len(backgrounds), 5)

    def test_custom_dark_background_uses_light_text(self):
        palette = palette_for("custom", "#102030")
        self.assertEqual(palette["BG"], "#102030")
        self.assertEqual(palette["FG"], "#F1F4F7")

    def test_custom_light_background_uses_dark_text(self):
        palette = palette_for("custom", "#F5EEDC")
        self.assertEqual(palette["BG"], "#F5EEDC")
        self.assertEqual(palette["FG"], "#17191C")

    def test_custom_colour_is_normalized(self):
        self.assertEqual(normalize_color("#aAbBcC"), "#AABBCC")

    def test_invalid_custom_colours_are_rejected(self):
        for value in ("red", "#123", "#12345678", "", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_color(value)

    def test_invalid_custom_palette_is_rejected(self):
        with self.assertRaises(ValueError):
            palette_for("custom", "not-a-colour")

    def test_unknown_theme_is_rejected(self):
        with self.assertRaises(ValueError):
            palette_for("space", "#123456")


if __name__ == "__main__":
    unittest.main(verbosity=2)
