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
    """Prefs JSON dosyası yolu, anahtar adları."""
    PATH: str              = os.path.join(os.path.expanduser("~"), ".remote_control_prefs.json")
    KEY_LOGGED_IN: str     = "is_logged_in"
    KEY_USER_ID: str       = "user_id"
    KEY_USERNAME: str      = "username"
    KEY_USER_ADDRESS: str  = "user_address"
    KEY_AUTH_TOKEN: str    = "auth_token"
    KEY_REMEMBERED_USERNAME: str = "remembered_username"  # geriye uyumluluk
    KEY_REMEMBERED_EMAIL: str = "remembered_email"
    KEY_USER_EMAIL: str = "user_email"
    KEY_USER_FIRST_NAME: str = "user_first_name"
    KEY_USER_LAST_NAME: str = "user_last_name"
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
    PING_INTERVAL_SEC:         int   = 25
    PING_TIMEOUT_SEC:          int   = 20
    HEARTBEAT_INTERVAL_MS:     int   = 30_000
    MJPEG_REQUEST_TIMEOUT_SEC: int   = 15
    MJPEG_CHUNK_SIZE:          int   = 65_536
    JPEG_MARKER_START:         bytes = b"\xff\xd8"
    JPEG_MARKER_END:           bytes = b"\xff\xd9"
    MJPEG_JOIN_TIMEOUT_SEC:    float = 2.0


# ──────────────────────────────────────────────────────────────────────────────
# Renk paleti — birleştirilmiş koyu modern tema
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Colors:
    """
    Tek renk kaynağı — tüm UI bileşenleri buradan referans alır.
    Nötr koyu gri zemin + canlı turuncu-kırmızı aksan.
    """

    # ── Arka planlar ────────────────────────────────────────────────────
    BG_APP:     str = "#181818"   # En koyu — pencere zemini
    BG_RAISED:  str = "#1E1E1E"   # Hafif yükseltilmiş yüzey (drawer vb.)
    BG_SURFACE: str = "#222222"   # Ana kart/panel yüzeyi
    BG_CARD:    str = "#262626"   # İç kart / liste öğesi
    BG_INPUT:   str = "#2A2A2A"   # Input alanı

    # ── Kenarlar ────────────────────────────────────────────────────────
    BORDER:        str = "#333333"   # Standart kenarlık
    BORDER_SUBTLE: str = "#2C2C2C"   # Neredeyse görünmez ayırıcı
    BORDER_INPUT:  str = "#3A3A3A"   # Input kenarlığı
    BORDER_FOCUS:  str = "#E85D3A"   # Odak (= accent)

    # ── Metin ───────────────────────────────────────────────────────────
    TEXT:        str = "#F0F0F0"   # Ana metin
    TEXT_MUTED:  str = "#A0A0A0"   # İkincil metin
    TEXT_SUBTLE: str = "#666666"   # Üçüncül / açıklama metni
    TEXT_DIM:    str = "#606060"   # Soluk/devre dışı metin
    TEXT_OFF:    str = "#555555"   # Çok soluk

    # ── Vurgu (turuncu-kırmızı) ─────────────────────────────────────────
    ACCENT:       str = "#E85D3A"
    ACCENT_HOVER: str = "#D04E2E"
    ACCENT_PRESS: str = "#B04028"
    ACCENT_DIM:   str = "#4A2A2A"

    # ── Durum: başarı (yeşil) ───────────────────────────────────────────
    SUCCESS:     str = "#4ADE80"   # Çevrimiçi göstergesi / onay
    SUCCESS_DIM: str = "rgba(74,222,128,0.35)"
    GREEN:       str = "#4ADE80"   # alias for SUCCESS
    GREEN_DIM:   str = "rgba(74,222,128,0.35)"

    # ── Durum: hata / tehlike (kırmızı) ────────────────────────────────
    ERROR:       str = "#F87171"   # Hata metni / tehlike göstergesi
    RED:         str = "#F87171"   # alias for ERROR
    WARNING:     str = "#FFCB70"   # Uyarı rengi

    # ── Buton yüzeyleri ─────────────────────────────────────────────────
    BTN_CONNECT_BG:    str = "#E85D3A"   # = ACCENT
    BTN_CONNECT_HOV:   str = "#D04E2E"   # = ACCENT_HOVER
    BTN_CONNECT_PRESS: str = "#B04028"   # = ACCENT_PRESS
    BTN_CONNECT_DIM:   str = "#4A2A2A"   # = ACCENT_DIM

    BTN_SEC_BG:  str = "#333333"
    BTN_SEC_BDR: str = "#3A3A3A"
    BTN_SEC_FG:  str = "#CCCCCC"
    BTN_SEC_HOV: str = "#3A3A3A"

    BTN_DANGER_BG:  str = "#3A2020"
    BTN_DANGER_BDR: str = "#662828"
    BTN_DANGER_FG:  str = "#FF6666"
    BTN_DANGER_HOV: str = "#442828"

    BTN_DISCONNECT_BG:  str = "#3A2020"
    BTN_DISCONNECT_BDR: str = "#662828"
    BTN_DISCONNECT_FG:  str = "#FF6666"
    BTN_DISCONNECT_HOV: str = "#442828"

    # Tuş kontrol buton renkleri
    BTN_NAV_BG:  str = "#2A3040"
    BTN_NAV_BDR: str = "#3A4A60"
    BTN_NAV_FG:  str = "#88AADD"

    BTN_VOL_BG:  str = "#203028"
    BTN_VOL_BDR: str = "#305040"
    BTN_VOL_FG:  str = "#66CC88"

    BTN_SCR_BG:  str = "#302838"
    BTN_SCR_BDR: str = "#4A3860"
    BTN_SCR_FG:  str = "#AA88CC"


# ──────────────────────────────────────────────────────────────────────────────
# Arayüz ölçüleri, mesajlar
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Ui:
    """Boyutlar ve mesajlar. Renkler için doğrudan Colors kullanın."""

    # Panel ölçüleri
    LEFT_PANEL_WIDTH:    int = 260
    SPLITTER_LEFT_SIZE:  int = 260
    SPLITTER_RIGHT_SIZE: int = 760
    HEADER_HEIGHT:       int = 48
    TOUCH_THRESHOLD_PX:  int = 8
    COORD_PRECISION:     int = 4

    # Renk proxy'leri (Colors sınıfından; geriye dönük uyumluluk)
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
    BTN_CAM_ON_BG:        str = Colors.BTN_VOL_BG
    BTN_CAM_ON_BORDER:    str = Colors.BTN_VOL_BDR
    BTN_CAM_OFF_BG:       str = Colors.BTN_DANGER_BG
    BTN_CAM_OFF_BORDER:   str = Colors.BTN_DANGER_BDR

    # Mesajlar
    MSG_WAITING:                str = "Bağlantı bekleniyor"
    MSG_CONNECTING:             str = "Sunucuya bağlanıyor..."
    MSG_SERVER_CONNECTED:       str = "Sunucuya bağlandı - Telefon bekleniyor..."
    MSG_PAIRED_WS:              str = "Bağlandı - Ekran görüntüsü aktarılıyor"
    MSG_PAIRED_WAIT_STREAM:     str = "Bağlandı - Yayın bekleniyor"
    MSG_PAIRED_A11Y_OFF:        str = "Bağlandı - Telefonda erişilebilirlik kapalı; ekran paylaşımı için açın"
    MSG_DISCONNECT_TIMEOUT:     str = "Bağlantı kesildi - Sunucu yanıt vermiyor."
    MSG_PEER_DISCONNECTED:      str = "Telefon bağlantısı kesildi."
    MSG_STREAM_STOPPED:         str = "Akış durdu."
    MSG_CODE_MUST_BE_12_DIGITS: str = "12 haneli sabit adresi girin."
    PLACEHOLDER_CODE:           str = "12 haneli sabit adresi girin"


# ──────────────────────────────────────────────────────────────────────────────
# Android KeyEvent kodları
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AndroidKeyCodes:
    """
    Android KeyEvent sabitleri.
    button_specs() → (etiket, renk_grubu, grid_satır, grid_sütun, key_id, colspan)
    """
    BACK:     int = 4
    HOME:     int = 3
    RECENTS:  int = 187
    VOL_UP:   int = 24
    VOL_DOWN: int = 25
    VOL_MUTE: int = 164
    POWER:    int = 26
    WAKEUP:   int = 224

    @classmethod
    def as_mapping(cls) -> Dict[str, int]:
        return {
            "key_back":     cls.BACK,
            "key_home":     cls.HOME,
            "key_recents":  cls.RECENTS,
            "key_vol_up":   cls.VOL_UP,
            "key_vol_down": cls.VOL_DOWN,
            "key_vol_mute": cls.VOL_MUTE,
        }

    @classmethod
    def button_specs(cls) -> List[Tuple[str, str, int, int, str, int]]:
        """(Etiket, renk_grubu, satır, sütun, key_id, colspan)"""
        return [
            ("Geri",        "nav", 0, 0, "key_back",     1),
            ("Ana Ekran",   "nav", 0, 1, "key_home",     1),
            ("Uygulamalar", "nav", 1, 0, "key_recents",  1),
            ("Sessize al",  "vol", 1, 1, "key_vol_mute", 1),
            ("Ses +",       "vol", 2, 0, "key_vol_up",   1),
            ("Ses −",       "vol", 2, 1, "key_vol_down", 1),
        ]
