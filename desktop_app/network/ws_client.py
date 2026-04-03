# ws_client.py
from __future__ import annotations

import json
import base64
import logging
import threading
import websocket
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage

from desktop_app.config import Network
from desktop_app.config.prefs_store import (
    clear_paired_phone_id,
    load_or_create_device_id,
    load_paired_phone_id as _load_paired_phone_id,
    save_paired_phone_id,
)

logger = logging.getLogger(__name__)


class WsClient(QObject):
    connected = pyqtSignal()
    disconnected = pyqtSignal(str)
    paired = pyqtSignal(str)
    peer_disconnected = pyqtSignal()
    command_received = pyqtSignal(dict)
    error_occurred = pyqtSignal(str, str)
    frame_received = pyqtSignal(QPixmap)
    paired_devices_status = pyqtSignal(list, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._session_code: str = ""
        self._frame_processing: bool = False
        self._disconnect_emitted: bool = False
        self.device_id: str = load_or_create_device_id()
        logger.info("PC device_id: %s", self.device_id)

    def connect_to_server(self, url: str, code: str) -> None:
        self.disconnect()
        self._session_code = code
        self._disconnect_emitted = False
        self._start_ws(url, on_open=self._on_open_join)

    def connect_with_device_id(self, url: str) -> None:
        self.disconnect()
        self._session_code = ""
        self._disconnect_emitted = False
        self._start_ws(url, on_open=self._on_open_device_hello)

    def disconnect(self, send_logout: bool = False) -> None:
        if self._ws and send_logout:
            self._send_json(
                {"type": "device_logout", "device_id": self.device_id},
                silent=True,
            )
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None

    def set_device_address(self, device_address: str | None) -> None:
        digits = "".join(ch for ch in (device_address or "") if ch.isdigit())[:12]
        self._device_address = digits or None

    def send_pair_confirm(self, target_device_id: str) -> None:
        self._send_json(
            {
                "type": "pair_confirm",
                "my_device_id": self.device_id,
                "paired_with": target_device_id,
            },
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

    def send_key_event(self, key_code: int) -> None:
        self.send_command({"action": "key_event", "key_code": key_code})

    def send_rotate_screen(self, landscape: bool) -> None:
        self.send_command({"action": "rotate_screen", "landscape": landscape})

    def send_heartbeat(self) -> None:
        self._send_json({"type": "heartbeat"}, silent=True)

    def send_request_presence(self) -> None:
        self._send_json({"type": "request_presence"}, silent=True)

    def _start_ws(self, url: str, *, on_open) -> None:
        self._ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_message=self._on_message,
            on_data=self._on_data,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs={"skip_utf8_validation": True},
            daemon=True,
        )
        self._thread.start()

    def _send_json(self, payload: dict, silent: bool = False) -> bool:
        ws = self._ws
        if ws is None:
            if not silent:
                self.error_occurred.emit("Baglanti acik degil.", "")
            return False
        try:
            ws.send(json.dumps(payload, separators=(",", ":")))
            return True
        except websocket.WebSocketConnectionClosedException:
            logger.warning("Kapali WebSocket'a mesaj gonderildi: %s", payload.get("type"))
            if not self._disconnect_emitted:
                self._disconnect_emitted = True
                self.disconnected.emit("socket is already closed")
            return False
        except Exception as exc:
            logger.error("WebSocket gonderim hatasi: %s", exc)
            if not silent:
                self.error_occurred.emit(str(exc), "")
            return False

    def _on_open_join(self, ws) -> None:
        if ws is not self._ws:
            return
        self.connected.emit()
        ws.send(
            json.dumps(
                {
                    "type": "join",
                    "code": self._session_code,
                    "role": "pc",
                    "device_id": self.device_id,
                },
                separators=(",", ":"),
            )
        )

    def _on_open_device_hello(self, ws) -> None:
        if ws is not self._ws:
            return
        self.connected.emit()
        payload: dict = {
            "type": "device_hello",
            "device_id": self.device_id,
            "role": "pc",
        }
        ws.send(json.dumps(payload, separators=(",", ":")))

    def _on_message(self, ws, raw) -> None:
        if ws is not self._ws:
            return

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("JSON decode hatasi: %s", raw[:100] if isinstance(raw, str) else raw)
            return

        msg_type = msg.get("type")
        if msg_type not in {"frame", "heartbeat"}:
            logger.debug("Mesaj alindi: type=%s", msg_type)

        if msg_type == "paired":
            partner_id = msg.get("partner_device_id", "")
            if partner_id:
                save_paired_phone_id(partner_id)
            self.paired.emit(msg.get("stream_url", ""))

        elif msg_type == "device_ack":
            paired_devices = msg.get("paired_devices", []) or []
            online_paired_devices = msg.get("online_paired_devices", []) or []
            self.paired_devices_status.emit(paired_devices, online_paired_devices)

        elif msg_type == "stream_info":
            self.paired.emit(msg.get("url", ""))

        elif msg_type == "frame":
            data_str = msg.get("data", "")
            if not data_str:
                return
            try:
                self._handle_frame_bytes(base64.b64decode(data_str))
            except Exception as e:
                logger.warning("Frame decode hatasi: %s", e)

        elif msg_type == "peer_disconnected":
            self.peer_disconnected.emit()

        elif msg_type == "command":
            self.command_received.emit(msg)

        elif msg_type == "error":
            code = str(msg.get("code") or "").strip()
            self.error_occurred.emit(msg.get("message", "Bilinmeyen hata"), code)

    def _on_data(self, ws, raw_data, data_type, _continue_flag) -> None:
        if ws is not self._ws:
            return
        # websocket-client tarafinda binary frame'ler her zaman on_message'a dusmeyebiliyor.
        if data_type == websocket.ABNF.OPCODE_BINARY and isinstance(raw_data, (bytes, bytearray)):
            self._handle_frame_bytes(bytes(raw_data))

    def _on_error(self, ws, error) -> None:
        if ws is not self._ws:
            return
        if isinstance(error, websocket.WebSocketConnectionClosedException):
            logger.info("WebSocket kapali hata callback'i alindi")
            if not self._disconnect_emitted:
                self._disconnect_emitted = True
                self.disconnected.emit("socket is already closed")
            return
        self.error_occurred.emit(str(error), "")

    def _on_close(self, ws, code, msg) -> None:
        if ws is not self._ws:
            return
        if not self._disconnect_emitted:
            self._disconnect_emitted = True
            self.disconnected.emit(f"code={code}, msg={msg}")

    def _handle_frame_bytes(self, jpeg_bytes: bytes) -> None:
        if self._frame_processing:
            return
        if (
            len(jpeg_bytes) < 4
            or not jpeg_bytes.startswith(Network.JPEG_MARKER_START)
            or not jpeg_bytes.endswith(Network.JPEG_MARKER_END)
        ):
            logger.debug("Gecersiz JPEG frame atlandi: %d bytes", len(jpeg_bytes))
            return
        self._frame_processing = True
        try:
            img = QImage()
            if img.loadFromData(jpeg_bytes, "JPEG"):
                pixmap = QPixmap.fromImage(img)
                if not pixmap.isNull():
                    self.frame_received.emit(pixmap)
                    logger.debug("Frame: %d bytes %dx%d", len(jpeg_bytes), img.width(), img.height())
            else:
                logger.warning("JPEG decode basarisiz")
        except Exception as e:
            logger.error("Frame decode hatasi: %s", e, exc_info=True)
        finally:
            self._frame_processing = False


def load_paired_phone_id() -> str | None:
    return _load_paired_phone_id()
