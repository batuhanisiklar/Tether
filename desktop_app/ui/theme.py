from desktop_app.config import Colors

FONT_STACK = "'Segoe UI', Arial, sans-serif"
MONO_FONT_STACK = "'Consolas', monospace"


def text_style(
    color: str,
    *,
    size: int = 13,
    weight: int | None = None,
    letter_spacing: float | None = None,
    background: str = "transparent",
    font_family: str = FONT_STACK,
    extra: str = "",
) -> str:
    parts = [
        f"color: {color}",
        f"font-size: {size}px",
        f"background: {background}",
        f"font-family: {font_family}",
    ]
    if weight is not None:
        parts.append(f"font-weight: {weight}")
    if letter_spacing is not None:
        parts.append(f"letter-spacing: {letter_spacing}px")
    if extra:
        parts.append(extra.strip().rstrip(";"))
    return "; ".join(parts) + ";"


def card_style(*, background: str | None = None, border_color: str | None = None, radius: int = 6) -> str:
    bg = background or Colors.BG_CARD
    border = border_color or Colors.BORDER
    return (
        f"background-color: {bg};"
        f" border: 1px solid {border};"
        f" border-radius: {radius}px;"
    )


def line_edit_style(
    *,
    font_size: int = 13,
    radius: int = 6,
    padding: str = "0 14px",
    centered: bool = False,
    letter_spacing: float | None = None,
) -> str:
    extra = "text-align: center;" if centered else ""
    letter_spacing_rule = f"letter-spacing: {letter_spacing}px;" if letter_spacing is not None else ""
    return f"""
        QLineEdit {{
            background-color: {Colors.BG_INPUT};
            border: 1px solid {Colors.BORDER_INPUT};
            border-radius: {radius}px;
            padding: {padding};
            color: {Colors.TEXT};
            font-size: {font_size}px;
            font-family: {FONT_STACK};
            selection-background-color: {Colors.ACCENT};
            {letter_spacing_rule}
            {extra}
        }}
        QLineEdit:focus {{
            border-color: {Colors.BORDER_FOCUS};
        }}
        QLineEdit[error="true"] {{
            border-color: {Colors.ERROR};
        }}
    """


def filled_button_style(
    *,
    background: str | None = None,
    foreground: str = "#FFFFFF",
    hover: str | None = None,
    pressed: str | None = None,
    disabled_background: str | None = None,
    disabled_foreground: str | None = None,
    radius: int = 6,
    font_size: int = 13,
    font_weight: int = 600,
) -> str:
    bg = background or Colors.ACCENT
    hov = hover or Colors.ACCENT_HOVER
    prs = pressed or Colors.ACCENT_PRESS
    dis_bg = disabled_background or Colors.ACCENT_DIM
    dis_fg = disabled_foreground or Colors.TEXT_OFF
    return f"""
        QPushButton {{
            background-color: {bg};
            color: {foreground};
            border: none;
            border-radius: {radius}px;
            font-size: {font_size}px;
            font-weight: {font_weight};
            font-family: {FONT_STACK};
        }}
        QPushButton:hover {{
            background-color: {hov};
        }}
        QPushButton:pressed {{
            background-color: {prs};
        }}
        QPushButton:disabled {{
            background-color: {dis_bg};
            color: {dis_fg};
        }}
    """


def outline_button_style(
    *,
    background: str | None = None,
    foreground: str | None = None,
    border_color: str | None = None,
    hover_background: str | None = None,
    hover_foreground: str | None = None,
    hover_border: str | None = None,
    radius: int = 6,
    font_size: int = 12,
    font_weight: int = 500,
) -> str:
    bg = background or Colors.BG_SURFACE
    fg = foreground or Colors.TEXT_MUTED
    border = border_color or Colors.BORDER
    hov_bg = hover_background or Colors.BG_CARD
    hov_fg = hover_foreground or Colors.TEXT
    hov_border = hover_border or Colors.ACCENT
    return f"""
        QPushButton {{
            background-color: {bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: {radius}px;
            font-size: {font_size}px;
            font-weight: {font_weight};
            font-family: {FONT_STACK};
        }}
        QPushButton:hover {{
            background-color: {hov_bg};
            color: {hov_fg};
            border-color: {hov_border};
        }}
    """


def tab_button_style(active: bool) -> str:
    if active:
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {Colors.ACCENT};
                border: none;
                border-bottom: 2px solid {Colors.ACCENT};
                font-size: 13px;
                font-weight: 600;
                font-family: {FONT_STACK};
                padding: 0 8px;
            }}
        """
    return f"""
        QPushButton {{
            background-color: transparent;
            color: {Colors.TEXT_MUTED};
            border: none;
            border-bottom: 2px solid transparent;
            font-size: 13px;
            font-weight: 500;
            font-family: {FONT_STACK};
            padding: 0 8px;
        }}
        QPushButton:hover {{
            color: {Colors.TEXT};
        }}
    """
