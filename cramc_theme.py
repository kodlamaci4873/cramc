"""CRAMC appearance palettes and safe custom-background colour derivation."""
from __future__ import annotations

import re
from typing import Dict

THEME_IDS = ("default", "ocean", "forest", "violet", "amoled", "custom")
THEME_LABELS = {
    "default": "Varsayılan",
    "ocean": "Okyanus",
    "forest": "Orman",
    "violet": "Mor",
    "amoled": "AMOLED siyahı",
    "custom": "Özel renk",
}

_PALETTES = {
    "default": {
        "BG": "#121212", "CARD": "#1c1c1f", "CARD2": "#232328",
        "CARD_BORDER": "#2a2a2f", "FG": "#e8e8ea", "FG_DIM": "#8b8b93",
    },
    "ocean": {
        "BG": "#081827", "CARD": "#10263a", "CARD2": "#17334d",
        "CARD_BORDER": "#24445f", "FG": "#e8f4ff", "FG_DIM": "#9db7cc",
    },
    "forest": {
        "BG": "#101d18", "CARD": "#182a21", "CARD2": "#20372b",
        "CARD_BORDER": "#31513e", "FG": "#eaf5ed", "FG_DIM": "#a5bca9",
    },
    "violet": {
        "BG": "#191326", "CARD": "#251b35", "CARD2": "#302344",
        "CARD_BORDER": "#49345f", "FG": "#f3edff", "FG_DIM": "#b8a9cc",
    },
    "amoled": {
        "BG": "#000000", "CARD": "#090909", "CARD2": "#121212",
        "CARD_BORDER": "#252525", "FG": "#f2f2f2", "FG_DIM": "#a0a0a0",
    },
}


def normalize_color(value: str) -> str:
    """Return uppercase #RRGGBB or raise ValueError."""
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
        raise ValueError("Expected a hexadecimal #RRGGBB colour")
    return value.strip().upper()


def _mix(first: str, second: str, amount: float) -> str:
    amount = max(0.0, min(1.0, float(amount)))
    a = tuple(int(first[index:index + 2], 16) for index in (1, 3, 5))
    b = tuple(int(second[index:index + 2], 16) for index in (1, 3, 5))
    values = tuple(round(x * (1 - amount) + y * amount) for x, y in zip(a, b))
    return "#{:02X}{:02X}{:02X}".format(*values)


def _luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def palette_for(theme_id: str = "default", custom_background: str | None = None) -> Dict[str, str]:
    """Build a complete palette; custom colours keep readable text and layered panels."""
    theme = str(theme_id or "default").casefold()
    if theme in _PALETTES:
        base = dict(_PALETTES[theme])
    elif theme == "custom":
        background = normalize_color(custom_background or "#121212")
        light = _luminance(background) >= 0.48
        foreground = "#17191C" if light else "#F1F4F7"
        dim = _mix(foreground, background, 0.38)
        panel_amount = 0.09 if light else 0.10
        card = _mix(background, "#000000" if light else "#FFFFFF", panel_amount)
        card2 = _mix(background, "#000000" if light else "#FFFFFF", panel_amount * 1.8)
        border = _mix(background, foreground, 0.22)
        base = {"BG": background, "CARD": card, "CARD2": card2,
                "CARD_BORDER": border, "FG": foreground, "FG_DIM": dim}
    else:
        raise ValueError(f"Unknown CRAMC theme: {theme_id}")

    dark = _luminance(base["BG"]) < 0.48
    panel = _mix(base["CARD"], "#000000" if dark else "#FFFFFF", 0.30)
    warning = "#F5A524"
    return {
        **base,
        "PANEL_BG": panel,
        "PANEL_FG": base["FG_DIM"],
        "WARNING_BG": _mix(base["BG"], warning, 0.15 if dark else 0.10),
        "WARNING_BORDER": _mix(base["BG"], warning, 0.42 if dark else 0.30),
        "NOTICE_BG": _mix(base["BG"], warning, 0.12 if dark else 0.08),
        "MUTED_FG": _mix(base["FG"], base["BG"], 0.46),
        "SUBTLE_FG": _mix(base["FG"], base["BG"], 0.68),
    }


__all__ = ["THEME_IDS", "THEME_LABELS", "normalize_color", "palette_for"]
