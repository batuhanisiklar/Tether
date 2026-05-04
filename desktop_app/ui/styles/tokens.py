"""Desktop UI design tokens."""

from desktop_app.config import Colors


class Spacing:
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24


class Radius:
    XS = 4
    SM = 6
    MD = 8
    LG = 10
    XL = 12


class Typography:
    FONT_STACK = "'Segoe UI', Arial, sans-serif"
    MONO_FONT_STACK = "'Consolas', monospace"
    SIZE_CAPTION = 11
    SIZE_BODY = 13
    SIZE_TITLE = 18


__all__ = ["Colors", "Spacing", "Radius", "Typography"]
