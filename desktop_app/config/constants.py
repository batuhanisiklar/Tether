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
    KEY_USER_ADDRESS: str  = "user_address"
    KEY_AUTH_TOKEN: str    = "auth_token"
    KEY_REMEMBERED_USERNAME: str = "remembered_username"  # geriye uyumluluk (eski tercih)
    KEY_REMEMBERED_EMAIL: str = "remembered_email"
    KEY_USER_EMAIL: str = "user_email"  # oturum acikken baslikta gosterilen e-posta
    KEY_DEVICE_ID: str     = "device_id"
    KEY_PAIRED_PHONE: str  = "paired_phone_id"
    KEY_PAIRED_PHONE_ADDRESS: str = "paired_phone_address"
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
    CODE_LENGTH: int  = 12


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
    Tek renk kaynağı — neutral koyu gri + turuncu aksan.
    app_window.py ve mobil tarafla birebir uyumlu.
    """
    # ── Arka planlar ─────────────────────────────────────────────────
    BG_APP:       str = "#1A1A1A"
    BG_SURFACE:   str = "#222222"
    BG_CARD:      str = "#2C2C2C"
    BG_INPUT:     str = "#2E2E2E"

    # ── Kenarlar ─────────────────────────────────────────────────────
    BORDER:       str = "#3A3A3A"
    BORDER_INPUT: str = "#444444"
    BORDER_FOCUS: str = "#E06040"

    # ── Metin ────────────────────────────────────────────────────────
    TEXT:         str = "#EEEEEE"
    TEXT_MUTED:   str = "#999999"
    TEXT_SUBTLE:  str = "#666666"
    TEXT_OFF:     str = "#555555"

    # ── Vurgu (turuncu) ──────────────────────────────────────────────
    ACCENT:       str = "#E06040"
    ACCENT_HOVER: str = "#D05535"
    ACCENT_PRESS: str = "#C04A2A"
    ACCENT_DIM:   str = "#5A3028"

    # ── Durum renkleri ───────────────────────────────────────────────
    SUCCESS:            str = "#55CC66"
    SUCCESS_HOVER:      str = "#4ABB5B"
    SUCCESS_PRESS:      str = "#3FAA50"
    SUCCESS_DIM:        str = "#2A4D30"
    ERROR:              str = "#FF4444"
    ERROR_HOVER:        str = "#EE3333"
    WARNING:            str = "#FFCB70"

    # ── Buton yüzeyleri ──────────────────────────────────────────────
    BTN_CONNECT_BG:    str = "#E06040"
    BTN_CONNECT_HOV:   str = "#D05535"
    BTN_CONNECT_PRESS: str = "#C04A2A"
    BTN_CONNECT_DIM:   str = "#5A3028"
    BTN_SEC_BG:        str = "#333333"
    BTN_SEC_BDR:       str = "#444444"
    BTN_SEC_FG:        str = "#CCCCCC"
    BTN_SEC_HOV:       str = "#3A3A3A"

    BTN_DANGER_BG:     str = "#3A2020"
    BTN_DANGER_BDR:    str = "#662828"
    BTN_DANGER_FG:     str = "#FF6666"
    BTN_DANGER_HOV:    str = "#442828"

    BTN_DISCONNECT_BG: str = "#3A2020"
    BTN_DISCONNECT_BDR: str = "#662828"
    BTN_DISCONNECT_FG: str = "#FF6666"
    BTN_DISCONNECT_HOV: str = "#442828"

    # Tuş kontrol buton renkleri
    BTN_NAV_BG:        str = "#2A3040"
    BTN_NAV_BDR:       str = "#3A4A60"
    BTN_NAV_FG:        str = "#88AADD"

    BTN_VOL_BG:        str = "#203028"
    BTN_VOL_BDR:       str = "#305040"
    BTN_VOL_FG:        str = "#66CC88"

    BTN_SCR_BG:        str = "#302838"
    BTN_SCR_BDR:       str = "#4A3860"
    BTN_SCR_FG:        str = "#AA88CC"


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
    MSG_CODE_MUST_BE_12_DIGITS: str = "12 haneli sabit adresi girin."
    PLACEHOLDER_CODE:           str = "12 haneli sabit adresi girin"


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
