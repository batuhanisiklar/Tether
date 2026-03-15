"""
Desktop App — Tüm sabitler.
Tek kaynak: tüm renkler, ölçüler, mesajlar ve Android key kodları burada.
login_window.py dahil tüm dosyalar buraya referans verir.
"""

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
# Renk paleti — Professional Dark  (AnyDesk / TeamViewer tarzı)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Colors:
    """
    Tek renk kaynağı. Ui ve LoginWindow burayı referans alır.
    '#' ile başlayan hex string'ler, PyQt stylesheet'te doğrudan kullanılır.
    """
    # ── Arka planlar ─────────────────────────────────────────────────
    BG_APP:       str = "#13151A"   # En koyu katman — pencere arka planı
    BG_SURFACE:   str = "#1A1D23"   # Header, sol panel
    BG_CARD:      str = "#1E2128"   # GroupBox, kart içi
    BG_INPUT:     str = "#242731"   # Input alanları

    # ── Kenarlar ─────────────────────────────────────────────────────
    BORDER:       str = "#2D3139"   # Genel ince kenar
    BORDER_INPUT: str = "#353944"   # Input kenarı
    BORDER_FOCUS: str = "#2B7FFF"   # Odak (mavi)

    # ── Metin ────────────────────────────────────────────────────────
    TEXT:         str = "#E8EAED"   # Birincil metin
    TEXT_MUTED:   str = "#8B8FA8"   # Soluk / yardımcı metin
    TEXT_SUBTLE:  str = "#6B7080"   # Alan başlıkları, footer
    TEXT_OFF:     str = "#50545F"   # Bağlı değil, devre dışı

    # ── Vurgu ────────────────────────────────────────────────────────────────
    ACCENT:       str = "#2B7FFF"   # Mavi — primary action
    ACCENT_HOVER: str = "#1A6FEF"
    ACCENT_PRESS: str = "#1260D5"
    ACCENT_DIM:   str = "#1F3A66"   # Disabled primary

    # ── Durum renkleri — Bağlan (yeşil), Bağlantıyı Kes (kırmızı) ───────────────────
    SUCCESS:            str = "#22C55E"   # Bağlan butonu, bağlı durum indikatörü
    SUCCESS_HOVER:      str = "#16A34A"
    SUCCESS_PRESS:      str = "#15803D"
    SUCCESS_DIM:        str = "#14402A"   # Bağlan disabled
    ERROR:              str = "#EF4444"   # Bağlantıyı Kes butonu, hata
    ERROR_HOVER:        str = "#DC2626"
    WARNING:            str = "#FF9F0A"

    # ── Buton yüzeyleri ──────────────────────────────────────────────
    BTN_CONNECT_BG:    str = "#22C55E"   # Bağlan — yeşil
    BTN_CONNECT_HOV:   str = "#16A34A"
    BTN_CONNECT_PRESS: str = "#15803D"
    BTN_CONNECT_DIM:   str = "#14402A"   # disabled gri-yeşil
    BTN_SEC_BG:   str = "#242731"   # İkincil buton zemini
    BTN_SEC_BDR:  str = "#353944"   # İkincil buton kenarı
    BTN_SEC_FG:   str = "#C0C4D0"   # İkincil buton metni
    BTN_SEC_HOV:  str = "#2D3139"   # İkincil hover

    BTN_DANGER_BG:  str = "#2D1515"  # Tehlikeli eylem zemini
    BTN_DANGER_BDR: str = "#5A2020"  # Tehlikeli kenar
    BTN_DANGER_FG:  str = "#FF453A"  # Tehlikeli metin
    BTN_DANGER_HOV: str = "#3D1F1F"  # Tehlikeli hover

    BTN_DISCONNECT_BG:  str = "#3D1515"   # Bağlantıyı Kes zemini (daha belirgin kırmızı)
    BTN_DISCONNECT_BDR: str = "#7F1D1D"
    BTN_DISCONNECT_FG:  str = "#EF4444"   # parlak kırmızı metin
    BTN_DISCONNECT_HOV: str = "#4D1A1A"

    # Tuş kontrol buton renkleri (gruba göre renk ayrımı)
    BTN_NAV_BG:   str = "#1E2740"   # Navigasyon (mavi tonu)
    BTN_NAV_BDR:  str = "#2B4080"
    BTN_NAV_FG:   str = "#7AABFF"

    BTN_VOL_BG:   str = "#1E2A1E"   # Ses (yeşil tonu)
    BTN_VOL_BDR:  str = "#2A5A2A"
    BTN_VOL_FG:   str = "#5EC472"

    BTN_SCR_BG:   str = "#2A1E2A"   # Ekran (mor tonu)
    BTN_SCR_BDR:  str = "#4A2A5A"
    BTN_SCR_FG:   str = "#B87FD4"


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
    SCREEN_PLACEHOLDER_FG: str = "#3D4050"
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
