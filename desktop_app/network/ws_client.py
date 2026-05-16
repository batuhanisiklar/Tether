from __future__ import annotations

import json
import base64
import logging
import threading
import time
import websocket
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from desktop_app.config import Network
from desktop_app.config.prefs_store import (
    clear_paired_phone_id,
    load_or_create_device_id,
    load_paired_phone_id,
    save_paired_phone_id,
)

logger = logging.getLogger(__name__)


class WsClient(QObject):
    """Eski sunucu sürümlerinde `device_ack` içinde `phone_accessibility_enabled` yoksa bu sentinel kullanılır."""
    PHONE_A11Y_UNCHANGED = object()

    connected = pyqtSignal()
    disconnected = pyqtSignal(str)
    paired = pyqtSignal(str)
    peer_disconnected = pyqtSignal()
    command_received = pyqtSignal(dict)
    error_occurred = pyqtSignal(str, str)
    frame_received = pyqtSignal(bytes)
    audio_received = pyqtSignal(bytes)
    rotation_received = pyqtSignal(int)        # Telefon rotasyonu (0/90/180/270 derece)
    paired_devices_status = pyqtSignal(list, list, object)
    session_rtt_ms = pyqtSignal(float)
    reconnecting = pyqtSignal(int)             # Yeniden bağlanma denemesi numarası

    # ── Reconnect sabitleri ──────────────────────────────────────────────
    _MAX_RECONNECT_ATTEMPTS = 10
    _RECONNECT_BASE_MS = 1500
    _RECONNECT_MAX_MS = 15000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._session_code: str = ""
        self._disconnect_emitted: bool = False
        self.device_id: str = load_or_create_device_id()
        self._ping_sent_at: dict[int, float] = {}
        self._ping_seq: int = 0
        self._last_paired_url: str = ""
        self._last_paired_time: float = 0.0
        self._PAIRED_DEBOUNCE_SEC: float = 2.0
        self._auth_token: str = ""

        # ── Reconnect durumu ─────────────────────────────────────────────
        self._last_url: str = ""
        self._last_on_open = None
        self._reconnect_attempt: int = 0
        self._reconnect_enabled: bool = False

        logger.info("PC device_id: %s", self.device_id)

    @property
    def join_session_code(self) -> str:
        return self._session_code

    def connect_to_server(self, url: str, code: str) -> None:
        self.disconnect()
        self._session_code = code
        self._disconnect_emitted = False
        self._last_url = url
        self._reconnect_attempt = 0
        self._reconnect_enabled = True
        self._last_paired_url = ""
        self._last_paired_time = 0.0
        self._start_ws(url, on_open=self._on_open_join)

    def connect_with_device_id(self, url: str) -> None:
        self.disconnect()
        self._session_code = ""
        self._disconnect_emitted = False
        self._last_url = url
        self._reconnect_attempt = 0
        self._reconnect_enabled = False  # Presence mode — reconnect yok, app timer yönetir
        self._start_ws(url, on_open=self._on_open_device_hello)

    def disconnect(self, send_logout: bool = False) -> None:
        self._reconnect_enabled = False
        self._reconnect_attempt = 0
        ws = self._ws
        if ws is None:
            return

        if send_logout:
            # Önce karşı tarafa oturumun kapandığını bildir, ardından kısa gecikmeyle socket'i kapat.
            # Bu gecikme düşük ağ kalitesinde "logout" paketinin düşmesini azaltır.
            self._send_json(
                self._with_auth({"type": "device_logout", "device_id": self.device_id}),
                silent=True,
            )
            QTimer.singleShot(120, self._finalize_disconnect)
            return

        self._finalize_disconnect()

    def _finalize_disconnect(self) -> None:
        ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        self._ws = None

    def set_device_address(self, device_address: str | None) -> None:
        digits = "".join(ch for ch in (device_address or "") if ch.isdigit())[:12]
        self._device_address = digits or None

    def set_auth_token(self, token: str | None) -> None:
        self._auth_token = (token or "").strip()

    def _with_auth(self, payload: dict) -> dict:
        if self._auth_token:
            return {**payload, "auth_token": self._auth_token}
        return payload

    def send_pair_confirm(self, target_device_id: str) -> None:
        self._send_json(
            self._with_auth({
                "type": "pair_confirm",
                "my_device_id": self.device_id,
                "paired_with": target_device_id,
            }),
            silent=True,
        )
        save_paired_phone_id(target_device_id)

    def forget_paired_phone(self) -> None:
        clear_paired_phone_id()

    def send_command(self, cmd: dict) -> None:
        self._send_json({"type": "command", **cmd})

    def send_touch(self, x: float, y: float) -> None:
        self.send_command({"action": "touch", "x": x, "y": y})

    def send_swipe(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.send_command({"action": "swipe", "x1": x1, "y1": y1, "x2": x2, "y2": y2})

    def send_camera_on(self) -> None:
        self.send_command({"action": "camera_on"})

    def send_camera_off(self) -> None:
        self.send_command({"action": "camera_off"})

    def send_screen_capture_on(self) -> None:
        """Telefonda ekran paylaşımı iznini başlatır (eşleşme sonrası)."""
        self.send_command({"action": "screen_capture_on"})

    def send_key_event(self, key_code: int) -> None:
        self.send_command({"action": "key_event", "key_code": key_code})

    def send_rotate_screen(self, degrees: int) -> None:
        """Telefon aktivitesinin fiziksel yönünü ayarlar (0, 90, 180, 270)."""
        d = int(degrees) % 360
        if d < 0:
            d += 360
        self.send_command({"action": "rotate_screen", "degrees": d})

    def send_paste_text(self, text: str) -> None:
        """Telefonda odaklı metin alanına yapıştırma (erişilebilirlik gerekir)."""
        safe = (text or "")[:8000]
        self.send_command({"action": "paste_text", "text": safe})

    def send_session_ping(self) -> None:
        """Oturum gecikmesini ölçer — telefon `session_pong` ile yanıtlar."""
        self._ping_seq += 1
        pid = self._ping_seq
        self._ping_sent_at[pid] = time.perf_counter()
        self._send_json({"type": "session_ping", "ping_id": pid}, silent=True)

    def send_heartbeat(self) -> None:
        self._send_json({"type": "heartbeat"}, silent=True)

    def send_request_presence(self) -> None:
        self._send_json({"type": "request_presence"}, silent=True)

    def _start_ws(self, url: str, *, on_open) -> None:
        self._last_on_open = on_open
        self._ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs={
                "skip_utf8_validation": True,
                "ping_interval": 25,
                "ping_timeout": 20,
            },
            daemon=True,
        )
        self._thread.start()

    def _send_json(self, payload: dict, silent: bool = False) -> bool:
        ws = self._ws
        if ws is None:
            if not silent:
                self.error_occurred.emit("Bağlantı açık değil.", "")
            return False
        try:
            ws.send(json.dumps(payload, separators=(",", ":")))
            return True
        except websocket.WebSocketConnectionClosedException:
            logger.warning("Kapalı WebSocket'a mesaj gönderildi: %s", payload.get("type"))
            if not self._disconnect_emitted:
                self._disconnect_emitted = True
                self.disconnected.emit("socket is already closed")
            return False
        except Exception as exc:
            logger.error("WebSocket gönderim hatası: %s", exc)
            if not silent:
                self.error_occurred.emit(str(exc), "")
            return False

    def _on_open_join(self, ws) -> None:
        if ws is not self._ws:
            return
        self._reconnect_attempt = 0
        self.connected.emit()
        _s = lambda d: json.dumps(d, separators=(",", ":"))
        ws.send(_s(self._with_auth({"type": "device_hello", "device_id": self.device_id, "role": "pc"})))
        ws.send(_s(self._with_auth({
            "type": "join",
            "code": self._session_code,
            "role": "pc",
            "device_id": self.device_id,
        })))

    def _on_open_device_hello(self, ws) -> None:
        if ws is not self._ws:
            return
        self._reconnect_attempt = 0
        self.connected.emit()
        _s = lambda d: json.dumps(d, separators=(",", ":"))
        ws.send(_s(self._with_auth({"type": "device_hello", "device_id": self.device_id, "role": "pc"})))
        address = getattr(self, "_device_address", None) or self.device_id
        ws.send(_s(self._with_auth({
            "type": "join",
            "code": address,
            "role": "pc",
            "device_id": self.device_id,
        })))

    def _on_message(self, ws, raw) -> None:
        if ws is not self._ws:
            return

        if isinstance(raw, (bytes, bytearray)):
            if raw.startswith(b"{"):
                raw = raw.decode("utf-8", errors="ignore")
            else:
                self._handle_frame_bytes(bytes(raw))
                return

        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("JSON decode hatasi: %s", raw[:100] if isinstance(raw, str) else raw)
            return

        msg_type = str(msg.get("type") or "").lower()
        if msg_type not in {"frame", "heartbeat", "device_ack"}:
            logger.debug("Mesaj alindi: type=%s", msg_type)

        if msg_type == "paired":
            partner_id = msg.get("partner_device_id", "")
            if partner_id:
                save_paired_phone_id(partner_id)
            stream_url = msg.get("stream_url", "")
            # Boş stream_url ile gelen tekrarlayıcı paired mesajlarını debounce et
            now = time.perf_counter()
            if not stream_url and (now - self._last_paired_time) < self._PAIRED_DEBOUNCE_SEC:
                logger.debug("Tekrarlayan boş paired mesajı yoksayıldı (debounce)")
            else:
                self._last_paired_url = stream_url
                self._last_paired_time = now
                self.paired.emit(stream_url)

        elif msg_type == "device_ack":
            paired_devices = msg.get("paired_devices", []) or []
            online_paired_devices = msg.get("online_paired_devices", []) or []
            if "phone_accessibility_enabled" in msg:
                raw_a11y = msg.get("phone_accessibility_enabled")
                phone_a11y = None if raw_a11y is None else bool(raw_a11y)
            else:
                phone_a11y = WsClient.PHONE_A11Y_UNCHANGED
            self.paired_devices_status.emit(paired_devices, online_paired_devices, phone_a11y)

        elif msg_type == "stream_info":
            url = msg.get("url", "")
            if isinstance(url, str):
                logger.info("stream_info url=%r", url)
            stream_url = url if isinstance(url, str) else ""
            # stream_info ile gelen URL aynıysa ve kısa süre içinde tekrar geldiyse debounce et
            now = time.perf_counter()
            if (stream_url == self._last_paired_url
                    and stream_url
                    and (now - self._last_paired_time) < self._PAIRED_DEBOUNCE_SEC):
                logger.debug("Tekrarlayan stream_info mesajı yoksayıldı (debounce, url=%r)", stream_url)
            else:
                self._last_paired_url = stream_url
                self._last_paired_time = now
                self.paired.emit(stream_url)

        elif msg_type == "frame":
            data_str = msg.get("data", "")
            if not data_str:
                return
            try:
                raw_b64 = data_str if isinstance(data_str, str) else str(data_str)
                frame_data = base64.b64decode(raw_b64, validate=False)
                # JSON fallback karesinde rotation bilgisi
                rotation = int(msg.get("rotation", 0))
                rotation_deg = {0: 0, 1: 90, 2: 180, 3: 270}.get(rotation, 0)
                self.rotation_received.emit(rotation_deg)
                self.frame_received.emit(frame_data)
            except Exception as e:
                logger.warning("Frame decode hatasi: %s", e)

        elif msg_type == "peer_disconnected":
            self.peer_disconnected.emit()

        elif msg_type == "session_pong":
            try:
                pid = int(msg.get("ping_id", 0))
            except (TypeError, ValueError):
                pid = 0
            t0 = self._ping_sent_at.pop(pid, None)
            if t0 is not None:
                rtt_ms = (time.perf_counter() - t0) * 1000.0
                self.session_rtt_ms.emit(rtt_ms)

        elif msg_type == "command":
            action = str(msg.get("action") or "").strip()
            if action == "accessibility_error":
                code = str(msg.get("code") or "accessibility_required").strip()
                text = msg.get("message", "Telefonda Erişilebilirlik servisi kapalı.")
                logger.warning("Telefon erişilebilirlik hatası: %s", text)
                self.error_occurred.emit(text, code)
            else:
                self.command_received.emit(msg)

        elif msg_type == "error":
            code = str(msg.get("code") or "").strip()
            text = msg.get("message", "Bilinmeyen hata")
            logger.warning("Sunucu WS hata mesajı: %s (code=%s)", text, code or "-")
            self.error_occurred.emit(text, code)

    def _on_error(self, ws, error) -> None:
        if ws is not self._ws:
            return
        if isinstance(error, websocket.WebSocketConnectionClosedException):
            logger.info("WebSocket kapalı hata callback'i alındı")
            if not self._disconnect_emitted:
                self._disconnect_emitted = True
                self.disconnected.emit("socket is already closed")
            self._try_reconnect()
            return
        if isinstance(error, UnicodeDecodeError):
            logger.debug("UnicodeDecodeError ignored in websocket callback: %s", error)
            return
        self.error_occurred.emit(str(error), "")
        self._try_reconnect()

    def _on_close(self, ws, code, msg) -> None:
        if ws is not self._ws:
            return
        if not self._disconnect_emitted:
            self._disconnect_emitted = True
            self.disconnected.emit(f"code={code}, msg={msg}")
        self._try_reconnect()

    def _handle_frame_bytes(self, frame_bytes: bytes) -> None:
        if not frame_bytes:
            return
        try:
            prefix = frame_bytes[0]
            if prefix == 0x01:
                # Yeni format: [0x01, rotation_byte, ...jpeg_data...]
                # Eski format: [0x01, 0xFF, 0xD8, ...jpeg_data...] (rotation byte yok)
                # Ayrım: rotation byte 0-3 arası → yeni format; 0xFF → eski format
                if len(frame_bytes) >= 3 and frame_bytes[1] <= 0x03:
                    # Yeni format: byte[1] = rotation (0-3)
                    rotation_byte = frame_bytes[1]
                    rotation_deg = {0: 0, 1: 90, 2: 180, 3: 270}.get(rotation_byte, 0)
                    self.rotation_received.emit(rotation_deg)
                    self.frame_received.emit(bytes(frame_bytes[2:]))
                else:
                    # Eski format: byte[1] = JPEG başlangıcı (0xFF)
                    self.frame_received.emit(bytes(frame_bytes[1:]))
            elif prefix == 0x02:
                self.audio_received.emit(bytes(frame_bytes[1:]))
            elif prefix == 0xFF:  # Ham JPEG (0xFF 0xD8 ile başlar)
                self.frame_received.emit(bytes(frame_bytes))
        except Exception as e:
            logger.error("Binary frame emit hatasi: %s", e, exc_info=True)

    # ── Auto-reconnect ───────────────────────────────────────────────────
    def _try_reconnect(self) -> None:
        """
        Bağlantı koptuğunda otomatik yeniden bağlanma (exponential backoff).
        Yalnızca reconnect etkinken ve maksimum deneme aşılmamışken çalışır.
        """
        if not self._reconnect_enabled:
            return
        if self._reconnect_attempt >= self._MAX_RECONNECT_ATTEMPTS:
            logger.warning("Maksimum yeniden bağlanma denemesi aşıldı (%d)", self._MAX_RECONNECT_ATTEMPTS)
            self._reconnect_enabled = False
            return
        if not self._last_url or self._last_on_open is None:
            return

        self._reconnect_attempt += 1
        delay_ms = min(
            self._RECONNECT_BASE_MS * (2 ** (self._reconnect_attempt - 1)),
            self._RECONNECT_MAX_MS,
        )
        logger.info(
            "Yeniden bağlanma denemesi %d/%d — %d ms sonra",
            self._reconnect_attempt,
            self._MAX_RECONNECT_ATTEMPTS,
            delay_ms,
        )
        self.reconnecting.emit(self._reconnect_attempt)

        # Eski socket'ı temizle (disconnect çağrılmadan)
        self._ws = None
        self._disconnect_emitted = False

        QTimer.singleShot(delay_ms, self._do_reconnect)

    def _do_reconnect(self) -> None:
        """Zamanlayıcı tetiklenince gerçek yeniden bağlanmayı yap."""
        if not self._reconnect_enabled:
            return
        if self._ws is not None:
            # Arada zaten bağlandıysak iptal et
            return
        logger.info("Yeniden bağlanma başlatılıyor: %s", self._last_url)
        self._start_ws(self._last_url, on_open=self._last_on_open)

