"""
App Window — Stil sabitleri.
==============================
Tüm palette değerleri ve inline stylesheet stringleri tek dosyada toplanır.
Colors sınıfından referans alır; hiçbir renk burada tekrar tanımlanmaz.
"""

from desktop_app.config import Colors

# ── Kısa referanslar (okunabilirlik için) ────────────────────────────────────
_BG           = Colors.BG_APP
_BG_RAISED    = Colors.BG_RAISED
_BG_CARD      = Colors.BG_CARD
_BG_INPUT     = Colors.BG_INPUT
_BORDER       = Colors.BORDER
_BORDER_SUBTLE = Colors.BORDER_SUBTLE
_ACCENT       = Colors.ACCENT
_ACCENT_HOVER = Colors.ACCENT_HOVER
_GREEN        = Colors.GREEN
_GREEN_DIM    = Colors.GREEN_DIM
_RED          = Colors.RED
_TEXT         = Colors.TEXT
_TEXT_SEC     = Colors.TEXT_MUTED
_TEXT_DIM     = Colors.TEXT_DIM

# ── Layout sabit yükseklik/marj değerleri ───────────────────────────────────
MAIN_SHELL_MARGIN       = 10
WIN_CHROME_BAR_HEIGHT   = 36
MAIN_NAV_BAR_HEIGHT     = 38
MAIN_FOOTER_BAR_HEIGHT  = 28
PROFILE_DRAWER_TOP_OFFSET = (
    MAIN_SHELL_MARGIN + WIN_CHROME_BAR_HEIGHT + MAIN_NAV_BAR_HEIGHT
)
PROFILE_DRAWER_BOTTOM_GAP = MAIN_SHELL_MARGIN + MAIN_FOOTER_BAR_HEIGHT

# ── Sekme (nav) stilleri ─────────────────────────────────────────────────────
TAB_STYLE_ACTIVE = (
    f"QPushButton {{ background: transparent; color: {_TEXT}; border: none;"
    f" border-bottom: 2px solid {_ACCENT}; font-size: 12px; font-weight: 600;"
    f" padding: 6px 14px 4px 14px; }}"
)
TAB_STYLE_INACTIVE = (
    f"QPushButton {{ background: transparent; color: {_TEXT_SEC}; border: none;"
    f" border-bottom: 2px solid transparent; font-size: 12px; font-weight: 500;"
    f" padding: 6px 14px 4px 14px; }}"
    f" QPushButton:hover {{ color: {_TEXT}; }}"
)

# ── Remote sayfası — birincil (turuncu gradyan) buton ───────────────────────
REMOTE_BTN_PRIMARY_SS = f"""
    QPushButton {{
        color: #FFFFFF;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F07858, stop:1 {_ACCENT_HOVER});
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 10px;
        font-size: 14px;
        font-weight: 700;
        padding: 0 18px;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #FF8A6A, stop:1 {_ACCENT});
        border-color: rgba(255, 255, 255, 0.24);
    }}
    QPushButton:pressed {{ background: {_ACCENT_HOVER}; padding-top: 1px; }}
    QPushButton:disabled {{
        background: #3D3D3D; color: #777777; border-color: #505050;
    }}
"""

# ── Remote sayfası — ikon/ok birincil buton ──────────────────────────────────
REMOTE_BTN_ICON_PRIMARY_SS = f"""
    QPushButton {{
        color: #FFFFFF;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F07858, stop:1 {_ACCENT_HOVER});
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 10px;
        font-size: 15px;
        font-weight: 700;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #FF8A6A, stop:1 {_ACCENT});
        border-color: rgba(255, 255, 255, 0.24);
    }}
    QPushButton:pressed {{ background: {_ACCENT_HOVER}; }}
    QPushButton:disabled {{
        background: #3D3D3D; color: #777777; border-color: #505050;
    }}
"""

# ── Remote sayfası — tehlike (bağlantı kes) butonu ──────────────────────────
REMOTE_BTN_DANGER_SS = f"""
    QPushButton {{
        color: #FFB8B8;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #4A2A2A, stop:1 #3A2222);
        border: 1px solid rgba(248, 113, 113, 0.35);
        border-radius: 10px;
        font-size: 14px;
        font-weight: 700;
        padding: 0 14px;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #5C3434, stop:1 #452828);
        border-color: rgba(248, 113, 113, 0.55);
    }}
    QPushButton:pressed {{ background: #361818; }}
    QPushButton:disabled {{
        background-color: {_BG_INPUT};
        color: {_TEXT_DIM};
        border-color: {_BORDER_SUBTLE};
    }}
"""

# ── Remote sayfası — hayalet (gri zemin) buton ──────────────────────────────
REMOTE_BTN_GHOST_SS = f"""
    QPushButton {{
        color: {_TEXT_SEC};
        background-color: {_BG_INPUT};
        border: 1px solid {_BORDER};
        border-radius: 10px;
        font-size: 14px;
        font-weight: 700;
        padding: 8px 10px;
    }}
    QPushButton:hover {{
        background-color: #383838; color: {_TEXT}; border-color: #555555;
    }}
    QPushButton:pressed {{ background-color: #303030; }}
    QPushButton:disabled {{ color: {_TEXT_DIM}; border-color: {_BORDER_SUBTLE}; }}
"""

# ── Remote sayfası — tuş kontrol butonu ─────────────────────────────────────
REMOTE_KEY_BTN_SS = f"""
    QPushButton {{
        background-color: {_BG_INPUT};
        color: {_TEXT_SEC};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        font-size: 12px;
        font-weight: 700;
        padding: 8px 4px;
    }}
    QPushButton:hover {{
        background-color: #3A3A3A; color: {_TEXT}; border-color: #555555;
    }}
    QPushButton:disabled {{ color: {_TEXT_DIM}; }}
"""

# ── Profil drawer — kapat butonu ────────────────────────────────────────────
PROFILE_DRAWER_CLOSE_BTN_SS = f"""
    QPushButton {{
        color: {_TEXT};
        background-color: {_BG_INPUT};
        border: 1px solid {_BORDER};
        border-radius: 10px;
        font-size: 11px;
        font-weight: 700;
        padding: 0 16px;
        min-height: 32px;
    }}
    QPushButton:hover {{
        background-color: #3A3A3A;
        border-color: {_ACCENT};
        color: {_TEXT};
    }}
    QPushButton:pressed {{ background-color: #2C2C2C; }}
"""

# ── Pencere / hesap buton eleman stilleri ───────────────────────────────────
WIN_TOOL_BTN_SS = f"""
    QPushButton {{
        background: transparent; color: {_TEXT_SEC}; border: none;
        border-radius: 8px; font-size: 16px; font-weight: 500;
        min-width: 38px; min-height: 28px;
    }}
    QPushButton:hover {{ background-color: rgba(255,255,255,0.08); color: {_TEXT}; }}
"""

WIN_CLOSE_BTN_SS = f"""
    QPushButton {{
        background: transparent; color: {_TEXT_SEC}; border: none;
        border-radius: 8px; font-size: 17px; font-weight: 600;
        min-width: 38px; min-height: 28px;
    }}
    QPushButton:hover {{ background-color: rgba(248,113,113,0.22); color: {_RED}; }}
"""

ACCOUNT_BTN_SS = f"""
    QPushButton {{
        background: transparent; color: {_TEXT_SEC};
        border: 1px solid {_BORDER};
        border-radius: 4px; font-size: 11px; padding: 0 10px;
    }}
    QPushButton:hover {{ color: {_TEXT}; border-color: #555; }}
"""

# ── Genel uygulama stylesheet ────────────────────────────────────────────────
GLOBAL_STYLESHEET = f"""
    QMainWindow {{ background-color: {_BG}; }}
    QWidget {{
        background: transparent;
        color: {_TEXT};
        font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    }}
    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{
        background: {_BG}; width: 6px; border: none;
    }}
    QScrollBar::handle:vertical {{
        background: #444; border-radius: 3px; min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

# ── DeviceCard online/offline stili (fonksiyon şeklinde) ────────────────────
def device_card_style(online: bool) -> str:
    border_color = _GREEN_DIM if online else _BORDER_SUBTLE
    border_hover  = _GREEN if online else _BORDER
    return (
        f"DeviceCard {{"
        f"  background-color: {_BG_CARD};"
        f"  border: 1px solid {border_color};"
        f"  border-radius: 8px;"
        f"}}"
        f"DeviceCard:hover {{ border-color: {border_hover}; }}"
    )

# ── Uyarı banner — kapat butonu ─────────────────────────────────────────────
WARNING_CLOSE_BTN_SS = f"""
    QPushButton {{
        color: #FFCCCC;
        background-color: rgba(248,113,113,0.16);
        border: none;
        border-radius: 10px;
        font-size: 11px;
        font-weight: 700;
        padding: 0 12px;
        min-width: 64px;
    }}
    QPushButton:hover {{
        background-color: rgba(248,113,113,0.24);
    }}
    QPushButton:pressed {{ background-color: rgba(248,113,113,0.22); }}
"""
