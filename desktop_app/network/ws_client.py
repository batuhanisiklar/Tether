import json
import os
import uuid
import threading
import base64
import logging
import websocket
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage

from desktop_app.config import Network, Prefs
from desktop_app.config.prefs_store import clear_paired_phone_id, load_paired_phone_id as _load_paired_phone_id
from desktop_app.config.prefs_store import read_prefs, save_paired_phone_id, write_prefs

logger = logging.getLogger(__name__)


def _load_or_create_device_id() -> str:
    """PC için kalıcı device_id okur; yoksa UUID oluşturup kaydeder."""
    prefs = read_prefs()

    if Prefs.KEY_DEVICE_ID in prefs:
        return prefs[Prefs.KEY_DEVICE_ID]

    device_id = f"pc-{uuid.uuid4().hex[:12]}"
    prefs[Prefs.KEY_DEVICE_ID] = device_id
    write_prefs(prefs)
    return device_id


class WsClient(QObject):
    """Signaling sunucusuyla ve (relay üzerinden) telefonla WebSocket haberleşmesi."""

    connected = pyqtSignal()                    # Sunucuya bağlandı
    disconnected = pyqtSignal(str)              # Bağlantı kesildi (sebep)
    paired = pyqtSignal(str)                    # Telefon ile eşleşildi (stream URL)
    auto_paired = pyqtSignal(str)               # Kayıtlı telefon otomatik bağlandı (partner device_id)
    peer_disconnected = pyqtSignal()            # Telefon bağlantısı kesildi
    command_received = pyqtSignal(dict)         # Telefondan komut geldi
    error_occurred = pyqtSignal(str)            # Hata mesajı
    frame_received = pyqtSignal(QPixmap)        # WebSocket üzerinden JPEG frame
    paired_devices_status = pyqtSignal(list, list)  # tum paired ids, online olanlar

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._session_code: str = ""
        self._frame_processing: bool = False  # Frame throttle bayrağı
        self._preferred_partner_id: str | None = None
        self._disconnect_emitted = False
        self.device_id: str = _load_or_create_device_id()
        logger.info(f"PC device_id: {self.device_id}")

    # ─── PUBLIC API ────────────────────────────────────────────────────────────

    def connect_to_server(self, url: str, code: str):
        """
        Signaling sunucusuna bağlan ve verilen kod ile join isteği gönder.

        :param url:  wss://... veya ws://...
        :param code: Telefon uygulamasının gösterdiği 6 haneli kod
        """
        self._session_code = code
        self._disconnect_emitted = False
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs={
                "ping_interval": Network.PING_INTERVAL_SEC,
                "ping_timeout": Network.PING_TIMEOUT_SEC,
                "skip_utf8_validation": True,
            },
            daemon=True,
        )
        self._thread.start()

    def connect_with_device_id(self, url: str, preferred_partner_id: str | None = None):
        """
        Sunucuya bağlan ve device_hello gönder (kayıtlı eşleşme varsa auto_paired tetiklenir).
        Kod girmeden otomatik yeniden bağlanma için kullanılır.
        """
        self._session_code = ""
        self._preferred_partner_id = preferred_partner_id
        self._disconnect_emitted = False
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open_device_hello,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs={
                "ping_interval": Network.PING_INTERVAL_SEC,
                "ping_timeout": Network.PING_TIMEOUT_SEC,
                "skip_utf8_validation": True,
            },
            daemon=True,
        )
        self._thread.start()

    def disconnect(self):
        """Bağlantıyı kapat."""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None

    def send_pair_confirm(self, phone_device_id: str):
        """İlk eşleşmeden sonra çağrılır; sunucuya kalıcı pairing kaydedilir."""
        self._send_json(
            {
                "type": "pair_confirm",
                "my_device_id": self.device_id,
                "paired_with": phone_device_id,
            },
            silent=True,
        )
        # Prefs'e kaydet
        save_paired_phone_id(phone_device_id)

    def send_command(self, cmd: dict):
        """Telefona komut gönder (relay üzerinden)."""
        payload = {"type": "command", **cmd}
        self._send_json(payload)

    def send_touch(self, x: float, y: float):
        """Dokunma koordinatını gönder (0.0–1.0 arası normalize)."""
        self.send_command({"action": "touch", "x": x, "y": y})

    def send_swipe(self, x1: float, y1: float, x2: float, y2: float):
        """Kaydırma olayı gönder."""
        self.send_command({"action": "swipe", "x1": x1, "y1": y1, "x2": x2, "y2": y2})

    def send_camera_on(self):
        """Kamerayı aç komutu."""
        self.send_command({"action": "camera_on"})

    def send_camera_off(self):
        """Kamerayı kapat komutu."""
        self.send_command({"action": "camera_off"})

    def send_key_event(self, key_code: int):
        """Android KeyEvent gönder."""
        self.send_command({"action": "key_event", "key_code": key_code})

    def send_rotate_screen(self, landscape: bool):
        """Telefon ekranını döndür (True=Yatay, False=Dikey)."""
        self.send_command({"action": "rotate_screen", "landscape": landscape})

    def send_heartbeat(self):
        """Keep-alive ping."""
        self._send_json({"type": "heartbeat"}, silent=True)

    def forget_paired_phone(self):
        clear_paired_phone_id()

    def _send_json(self, payload: dict, silent: bool = False) -> bool:
        current_ws = self._ws
        if current_ws is None:
            if not silent:
                self.error_occurred.emit("Baglanti acik degil.")
            return False
        try:
            current_ws.send(json.dumps(payload, separators=(",", ":")))
            return True
        except websocket.WebSocketConnectionClosedException:
            logger.warning("Kapali WebSocket'a mesaj gonderilmeye calisildi: %s", payload.get("type"))
            if not self._disconnect_emitted:
                self._disconnect_emitted = True
                self.disconnected.emit("socket is already closed")
            return False
        except Exception as exc:
            logger.error("WebSocket gonderim hatasi: %s", exc)
            if not silent:
                self.error_occurred.emit(str(exc))
            return False

    # ─── WEBSOCKET CALLBACKS ───────────────────────────────────────────────────

    def _on_open(self, ws):
        self.connected.emit()
        # PC olarak join isteği gönder (6-digit code flow)
        ws.send(json.dumps({
            "type": "join",
            "code": self._session_code,
            "role": "pc",
            "device_id": self.device_id,
        }, separators=(",", ":")))

    def _on_open_device_hello(self, ws):
        self.connected.emit()
        # device_hello ile tanıt — kayıtlı telefon çevrimiçiyse auto_paired gelir
        payload = {
            "type": "device_hello",
            "device_id": self.device_id,
            "role": "pc",
        }
        if self._preferred_partner_id:
            payload["preferred_partner_id"] = self._preferred_partner_id
        ws.send(json.dumps(payload, separators=(",", ":")))

    def _on_message(self, ws, raw):
        if isinstance(raw, (bytes, bytearray)):
            self._handle_frame_bytes(bytes(raw))
            return

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"JSON decode hatası: {raw[:100]}...")
            return

        msg_type = msg.get("type")
        if msg_type != "frame":
            logger.debug(f"Mesaj alındı: type={msg_type}")

        if msg_type == "paired":
            partner_id = msg.get("partner_device_id", "")
            if partner_id:
                save_paired_phone_id(partner_id)
            self.paired.emit(msg.get("stream_url", ""))

        elif msg_type == "auto_paired":
            partner_id = msg.get("partner_device_id", "")
            logger.info(f"Auto-paired with phone: {partner_id}")
            self.auto_paired.emit(partner_id)

        elif msg_type == "device_ack":
            paired_devices = msg.get("paired_devices", []) or []
            online_paired_devices = msg.get("online_paired_devices", []) or []
            self.paired_devices_status.emit(paired_devices, online_paired_devices)

        elif msg_type == "stream_info":
            self.paired.emit(msg.get("url", ""))

        elif msg_type == "frame":
            data_str = msg.get("data", "")
            if not data_str:
                logger.warning("Frame mesajı boş data içeriyor")
                return
            try:
                self._handle_frame_bytes(base64.b64decode(data_str))
            except Exception as e:
                logger.warning("Eski tip frame mesajı decode edilemedi: %s", e)

        elif msg_type == "peer_disconnected":
            self.peer_disconnected.emit()

        elif msg_type == "command":
            self.command_received.emit(msg)

        elif msg_type == "error":
            self.error_occurred.emit(msg.get("message", "Bilinmeyen hata"))

    def _on_error(self, ws, error):
        if isinstance(error, websocket.WebSocketConnectionClosedException) and not self._disconnect_emitted:
            self._disconnect_emitted = True
            self.disconnected.emit("socket is already closed")
        self.error_occurred.emit(str(error))

    def _on_close(self, ws, code, msg):
        if not self._disconnect_emitted:
            self._disconnect_emitted = True
            self.disconnected.emit(f"code={code}, msg={msg}")

    def _handle_frame_bytes(self, jpeg_bytes: bytes):
        if self._frame_processing:
            return
        self._frame_processing = True
        try:
            img = QImage()
            if img.loadFromData(jpeg_bytes, "JPEG"):
                pixmap = QPixmap.fromImage(img)
                if not pixmap.isNull():
                    self.frame_received.emit(pixmap)
                    logger.debug(f"Frame gönderildi: {len(jpeg_bytes)} bytes {img.width()}x{img.height()}")
            else:
                logger.warning("JPEG decode başarısız")
        except Exception as e:
            logger.error(f"Frame decode hatası: {e}", exc_info=True)
        finally:
            self._frame_processing = False


def load_paired_phone_id() -> str | None:
    """Prefs dosyasından kayıtlı eşleşmiş telefon device_id'sini okur."""
    return _load_paired_phone_id()
