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
# Renk paleti — yumusak pastel yuzeyler
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Colors:
    """
    Tek renk kaynağı. Ui ve LoginWindow burayı referans alır.
    '#' ile başlayan hex string'ler, PyQt stylesheet'te doğrudan kullanılır.
    """
    # ── Arka planlar ─────────────────────────────────────────────────
    BG_APP:       str = "#F3F5FB"
    BG_SURFACE:   str = "#FFFFFF"
    BG_CARD:      str = "#FAFBFF"
    BG_INPUT:     str = "#F5F7FD"

    # ── Kenarlar ─────────────────────────────────────────────────────
    BORDER:       str = "#D9E1EF"
    BORDER_INPUT: str = "#D4DDEE"
    BORDER_FOCUS: str = "#8695FF"

    # ── Metin ────────────────────────────────────────────────────────
    TEXT:         str = "#24324A"
    TEXT_MUTED:   str = "#6E7B95"
    TEXT_SUBTLE:  str = "#8D98AE"
    TEXT_OFF:     str = "#A2ACC0"

    # ── Vurgu ────────────────────────────────────────────────────────────────
    ACCENT:       str = "#7C8BFF"
    ACCENT_HOVER: str = "#6F7EF7"
    ACCENT_PRESS: str = "#6170E8"
    ACCENT_DIM:   str = "#CDD3FF"

    # ── Durum renkleri — Bağlan (yeşil), Bağlantıyı Kes (kırmızı) ───────────────────
    SUCCESS:            str = "#69B99C"
    SUCCESS_HOVER:      str = "#56AA8B"
    SUCCESS_PRESS:      str = "#489A7B"
    SUCCESS_DIM:        str = "#DDEFE7"
    ERROR:              str = "#E47D7D"
    ERROR_HOVER:        str = "#D56D6D"
    WARNING:            str = "#E5B35B"

    # ── Buton yüzeyleri ──────────────────────────────────────────────
    BTN_CONNECT_BG:    str = "#7C8BFF"
    BTN_CONNECT_HOV:   str = "#6F7EF7"
    BTN_CONNECT_PRESS: str = "#6170E8"
    BTN_CONNECT_DIM:   str = "#CDD3FF"
    BTN_SEC_BG:        str = "#FFFFFF"
    BTN_SEC_BDR:       str = "#D4DDEE"
    BTN_SEC_FG:        str = "#55627C"
    BTN_SEC_HOV:       str = "#F1F4FB"

    BTN_DANGER_BG:     str = "#FFF2F2"
    BTN_DANGER_BDR:    str = "#F1C7C7"
    BTN_DANGER_FG:     str = "#C96868"
    BTN_DANGER_HOV:    str = "#FFE7E7"

    BTN_DISCONNECT_BG: str = "#FFF4F4"
    BTN_DISCONNECT_BDR: str = "#EECACA"
    BTN_DISCONNECT_FG: str = "#CC6F6F"
    BTN_DISCONNECT_HOV: str = "#FFEAEA"

    # Tuş kontrol buton renkleri (gruba göre renk ayrımı)
    BTN_NAV_BG:        str = "#EEF2FF"
    BTN_NAV_BDR:       str = "#CDD6FF"
    BTN_NAV_FG:        str = "#6271DA"

    BTN_VOL_BG:        str = "#ECF8F2"
    BTN_VOL_BDR:       str = "#CBE8D9"
    BTN_VOL_FG:        str = "#4D9B7A"

    BTN_SCR_BG:        str = "#F6EEFF"
    BTN_SCR_BDR:       str = "#E0CCFF"
    BTN_SCR_FG:        str = "#9A74C8"


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
