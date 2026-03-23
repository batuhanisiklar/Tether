"""
Desktop App — Tüm sabitler.
Tek kaynak: tüm renkler, ölçüler, mesajlar ve Android key kodları burada.
login_window.py dahil tüm dosyalar buraya referans verir.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Uygulama kimliği
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AppMeta:
    NAME: str          = "Remote Phone Control"
    VERSION: str       = "1.0.0"
    WINDOW_TITLE: str  = "Remote Phone Control"
    MIN_WIDTH: int     = 1000
    MIN_HEIGHT: int    = 700
    DEFAULT_WIDTH: int = 1280
    DEFAULT_HEIGHT: int = 800


# ──────────────────────────────────────────────────────────────────────────────
# Tercihler / Kalıcı depolama
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Prefs:
    """Prefs JSON dosyası yolu, anahtar adları ve DB bağlantısı."""
    PATH: str              = os.path.join(os.path.expanduser("~"), ".remote_control_prefs.json")
    KEY_LOGGED_IN: str     = "is_logged_in"
    KEY_USER_ID: str       = "user_id"
    KEY_USERNAME: str      = "username"
    KEY_REMEMBERED_USERNAME: str = "remembered_username"
    KEY_DEVICE_ID: str     = "device_id"
    KEY_PAIRED_PHONE: str  = "paired_phone_id"
    DB_URL: str            = os.environ.get(
        "NEON_DB_URL",
        "postgresql://neondb_owner:npg_Y3JevV2SsERI@ep-crimson-sun-anqdvhsy-pooler.c-6.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Ağ / Signaling
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ServerDefaults:
    DEFAULT_URL: str  = "wss://connect-your-phone.onrender.com"
    CODE_LENGTH: int  = 6


@dataclass(frozen=True)
class Network:
    PING_INTERVAL_SEC:         int   = 20
    PING_TIMEOUT_SEC:          int   = 10
    HEARTBEAT_INTERVAL_MS:     int   = 30_000
    MJPEG_REQUEST_TIMEOUT_SEC: int   = 10
    MJPEG_CHUNK_SIZE:          int   = 4096
    JPEG_MARKER_START:         bytes = b"\xff\xd8"
    JPEG_MARKER_END:           bytes = b"\xff\xd9"
    MJPEG_JOIN_TIMEOUT_SEC:    float = 2.0


# ──────────────────────────────────────────────────────────────────────────────
# Renk paleti — koyu modern tema
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Colors:
    """
    Tek renk kaynağı. Ui ve LoginWindow burayı referans alır.
    '#' ile başlayan hex string'ler, PyQt stylesheet'te doğrudan kullanılır.
    """
    # ── Arka planlar ─────────────────────────────────────────────────
    BG_APP:       str = "#0F1220"
    BG_SURFACE:   str = "#161B2D"
    BG_CARD:      str = "#1C2238"
    BG_INPUT:     str = "#242C46"

    # ── Kenarlar ─────────────────────────────────────────────────────
    BORDER:       str = "#303A5C"
    BORDER_INPUT: str = "#3B486E"
    BORDER_FOCUS: str = "#8C96FF"

    # ── Metin ────────────────────────────────────────────────────────
    TEXT:         str = "#F2F5FF"
    TEXT_MUTED:   str = "#A8B2D1"
    TEXT_SUBTLE:  str = "#7984A8"
    TEXT_OFF:     str = "#5F6C93"

    # ── Vurgu ────────────────────────────────────────────────────────────────
    ACCENT:       str = "#8A95FF"
    ACCENT_HOVER: str = "#7B87F7"
    ACCENT_PRESS: str = "#6D78E8"
    ACCENT_DIM:   str = "#44508B"

    # ── Durum renkleri — Bağlan (yeşil), Bağlantıyı Kes (kırmızı) ───────────────────
    SUCCESS:            str = "#5FD1A4"
    SUCCESS_HOVER:      str = "#51C295"
    SUCCESS_PRESS:      str = "#43B286"
    SUCCESS_DIM:        str = "#224D41"
    ERROR:              str = "#FF8B8B"
    ERROR_HOVER:        str = "#F37F7F"
    WARNING:            str = "#FFCB70"

    # ── Buton yüzeyleri ──────────────────────────────────────────────
    BTN_CONNECT_BG:    str = "#8A95FF"
    BTN_CONNECT_HOV:   str = "#7B87F7"
    BTN_CONNECT_PRESS: str = "#6D78E8"
    BTN_CONNECT_DIM:   str = "#44508B"
    BTN_SEC_BG:        str = "#202845"
    BTN_SEC_BDR:       str = "#334066"
    BTN_SEC_FG:        str = "#D2D9F5"
    BTN_SEC_HOV:       str = "#273153"

    BTN_DANGER_BG:     str = "#312028"
    BTN_DANGER_BDR:    str = "#6A3D48"
    BTN_DANGER_FG:     str = "#FF9AA0"
    BTN_DANGER_HOV:    str = "#3B2630"

    BTN_DISCONNECT_BG: str = "#312028"
    BTN_DISCONNECT_BDR: str = "#6A3D48"
    BTN_DISCONNECT_FG: str = "#FF9AA0"
    BTN_DISCONNECT_HOV: str = "#3B2630"

    # Tuş kontrol buton renkleri (gruba göre renk ayrımı)
    BTN_NAV_BG:        str = "#20294A"
    BTN_NAV_BDR:       str = "#32447D"
    BTN_NAV_FG:        str = "#A7B4FF"

    BTN_VOL_BG:        str = "#1D302B"
    BTN_VOL_BDR:       str = "#2E5A4D"
    BTN_VOL_FG:        str = "#79D6B3"

    BTN_SCR_BG:        str = "#2A2140"
    BTN_SCR_BDR:       str = "#55427C"
    BTN_SCR_FG:        str = "#C4A5FF"


# ──────────────────────────────────────────────────────────────────────────────
# Arayüz ölçüleri, mesajlar — Colors'a referans verir
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Ui:
    """Boyutlar, mesajlar. Renkler için Colors kullanın."""
    # Panel
    LEFT_PANEL_WIDTH:    int = 260
    SPLITTER_LEFT_SIZE:  int = 260
    SPLITTER_RIGHT_SIZE: int = 760
    HEADER_HEIGHT:       int = 48
    TOUCH_THRESHOLD_PX:  int = 8
    COORD_PRECISION:     int = 4

    # Renk proxy'leri (Colors sınıfından taşınan, geriye dönük uyumluluk için)
    BG_MAIN:              str = Colors.BG_APP
    BG_HEADER_START:      str = Colors.BG_SURFACE
    BG_HEADER_END:        str = Colors.BG_SURFACE
    BG_INPUT:             str = Colors.BG_INPUT
    BG_CARD:              str = Colors.BG_CARD
    BG_LEFT_PANEL:        str = Colors.BG_SURFACE
    BORDER:               str = Colors.BORDER
    BORDER_INPUT:         str = Colors.BORDER_INPUT
    BORDER_FOCUS:         str = Colors.BORDER_FOCUS
    TEXT_PRIMARY:         str = Colors.TEXT
    TEXT_INPUT:           str = Colors.TEXT
    TEXT_MUTED:           str = Colors.TEXT_MUTED
    TEXT_LABEL:           str = Colors.TEXT_SUBTLE
    TEXT_ERROR:           str = Colors.ERROR
    TEXT_SUCCESS:         str = Colors.SUCCESS
    TEXT_DISCONNECTED:    str = Colors.TEXT_OFF
    ACCENT:               str = Colors.ACCENT
    ACCENT_GROUP:         str = Colors.TEXT_SUBTLE
    BTN_PRIMARY_BG:       str = Colors.ACCENT
    BTN_PRIMARY_HOVER:    str = Colors.ACCENT_HOVER
    BTN_PRIMARY_PRESSED:  str = Colors.ACCENT_PRESS
    BTN_PRIMARY_DISABLED: str = Colors.ACCENT_DIM
    BTN_DANGER_BG:        str = Colors.BTN_DANGER_BG
    BTN_DANGER_FG:        str = Colors.BTN_DANGER_FG
    BTN_DANGER_BORDER:    str = Colors.BTN_DANGER_BDR
    BTN_DANGER_HOVER:     str = Colors.BTN_DANGER_HOV
    BTN_SECONDARY_BG:     str = Colors.BTN_SEC_BG
    BTN_SECONDARY_BORDER: str = Colors.BTN_SEC_BDR
    BTN_SECONDARY_HOVER:  str = Colors.BTN_SEC_HOV
    BTN_SECONDARY_FG:     str = Colors.BTN_SEC_FG
    BTN_CONNECT_BG:       str = Colors.ACCENT
    BTN_CONNECT_HOVER:    str = Colors.ACCENT_HOVER
    BTN_CONNECT_PRESSED:  str = Colors.ACCENT_PRESS
    BTN_DISCONNECT_BG:    str = Colors.BTN_DANGER_BG
    BTN_DISCONNECT_HOVER: str = Colors.BTN_DANGER_HOV
    BTN_CONTROL_BG:       str = Colors.BTN_SEC_BG
    BTN_CONTROL_BORDER:   str = Colors.BTN_SEC_BDR
    BTN_CONTROL_HOVER_BG: str = Colors.BTN_SEC_HOV
    BTN_CONTROL_HOVER_BORDER: str = Colors.ACCENT
    BTN_ROTATE_BG:        str = Colors.BTN_NAV_BG
    BTN_ROTATE_BORDER:    str = Colors.BTN_NAV_BDR
    BTN_LOGOUT_BG:        str = Colors.BTN_DANGER_BG
    BTN_LOGOUT_FG:        str = Colors.BTN_DANGER_FG
    STATUS_BAR_BG:        str = Colors.BG_APP
    SPLITTER_HANDLE_BG:   str = Colors.BORDER
    SCREEN_BORDER:        str = Colors.BORDER
    SCREEN_PLACEHOLDER_FG: str = "#97A2B8"
    SCREEN_PLACEHOLDER_BG: str = Colors.BG_APP
    # Eski kamera sabitleri (geriye dönük uyumluluk)
    BTN_CAM_ON_BG:        str = Colors.BTN_VOL_BG
    BTN_CAM_ON_BORDER:    str = Colors.BTN_VOL_BDR
    BTN_CAM_OFF_BG:       str = Colors.BTN_DANGER_BG
    BTN_CAM_OFF_BORDER:   str = Colors.BTN_DANGER_BDR

    # Mesajlar
    MSG_WAITING:               str = "Bağlantı bekleniyor"
    MSG_CONNECTING:            str = "Sunucuya bağlanıyor..."
    MSG_SERVER_CONNECTED:      str = "Sunucuya bağlandı  —  Telefon bekleniyor..."
    MSG_PAIRED_WS:             str = "Bağlandı  —  Ekran görüntüsü aktarılıyor"
    MSG_DISCONNECT_TIMEOUT:    str = "Bağlantı kesildi  —  Sunucu yanıt vermiyor."
    MSG_PEER_DISCONNECTED:     str = "Telefon bağlantısı kesildi."
    MSG_STREAM_STOPPED:        str = "Akış durdu."
    MSG_CODE_MUST_BE_6_DIGITS: str = "Kod 6 haneli sayı olmalı."
    PLACEHOLDER_CODE:          str = "6 haneli bağlantı kodunu girin"


# ──────────────────────────────────────────────────────────────────────────────
# Android KeyEvent kodları
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AndroidKeyCodes:
    """
    Android KeyEvent sabitleri.
    button_specs() → (etiket, renk_grubu, grid_satır, grid_sütun, key_id)
    """
    BACK:     int = 4
    HOME:     int = 3
    RECENTS:  int = 187
    VOL_UP:   int = 24
    VOL_DOWN: int = 25
    POWER:    int = 26    # Ekranı kilitle / uyandır (toggle)
    WAKEUP:   int = 224   # KEYCODE_WAKEUP (henüz desteklenmiyor, POWER kullan)

    @classmethod
    def as_mapping(cls) -> Dict[str, int]:
        return {
            "key_back":    cls.BACK,
            "key_home":    cls.HOME,
            "key_recents": cls.RECENTS,
            "key_vol_up":  cls.VOL_UP,
            "key_vol_down":cls.VOL_DOWN,
            "key_power":   cls.POWER,
        }

    @classmethod
    def button_specs(cls) -> List[Tuple[str, str, int, int, str]]:
        """
        (Etiket, renk_grubu, satır, sütun, key_id)
        renk_grubu: 'nav' | 'vol' | 'screen'
        """
        return [
            # Navigasyon  (mavi tonu)
            ("Geri",        "nav",    0, 0, "key_back"),
            ("Ana Ekran",   "nav",    0, 1, "key_home"),
            ("Uygulamalar", "nav",    1, 0, "key_recents"),
            # Ses  (yeşil tonu)
            ("Ses +",       "vol",    1, 1, "key_vol_up"),
            ("Ses −",       "vol",    2, 0, "key_vol_down"),
            # Ekran  (mor tonu) — POWER hem açar hem kilitler
            ("Güç Tuşu",    "screen", 2, 1, "key_power"),
        ]
