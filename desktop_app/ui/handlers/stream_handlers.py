"""
Frame / audio / rotation olay isleyici mixin'i.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QImage, QPixmap

from desktop_app.config import Ui

logger = logging.getLogger(__name__)


class StreamHandlersMixin:
    """Frame alma, ses ve dondurme olaylari."""

    @pyqtSlot(bytes)
    def _on_audio_received(self, pcm_bytes: bytes):
        if self._phone_media_muted is True:
            return
        if self._audio_player is not None:
            self._audio_player.write_pcm(pcm_bytes)

    @pyqtSlot(bytes)
    def _on_frame_received(self, frame_bytes: bytes):
        if self._ws_mode != "session":
            return
        if not frame_bytes:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(frame_bytes, "JPEG"):
            if not pixmap.loadFromData(frame_bytes):
                img = QImage()
                if not img.loadFromData(frame_bytes):
                    logger.warning("Goruntu cozumlenemedi. Boyut: %d bayt", len(frame_bytes))
                    return
                pixmap = QPixmap.fromImage(img)
        if pixmap.isNull():
            return
        was_frame_visible = self._remote_frame_visible
        if not self._connected:
            self._set_connected(True)
            self._switch_page(1)
        self._remote_frame_visible = True
        self._screen.set_frame(pixmap)
        self._note_stream_frame(pixmap.width(), pixmap.height())
        if not was_frame_visible:
            self._refresh_paired_stream_status()

    # Rotation

    def _apply_rotation_step(self) -> None:
        deg = self._rotation_step * 90
        self._screen.set_rotation(deg)
        self._sync_stream_aspect_fit()

    @staticmethod
    def _normalize_rotation_step(degrees: int | float) -> int:
        """Her turlu derece degerini 0..3 adimina normalize et."""
        try:
            deg = int(degrees)
        except (TypeError, ValueError):
            deg = 0
        return ((deg % 360) // 90) % 4

    @pyqtSlot(int)
    def _on_rotation_received(self, degrees: int):
        """Telefon rotasyonu metadata'si gecici olarak yok sayilir (UI talebi)."""
        _ = degrees
        return

    # Stream status / aspect

    def _request_phone_screen_capture(self) -> None:
        if self._connected:
            self._ws_client.send_screen_capture_on()

    def _refresh_paired_stream_status(self) -> None:
        if not self._connected:
            return
        if self._remote_frame_visible:
            if self._phone_accessibility_enabled is False:
                logger.debug("Kare akisi aktif - erisilebilirlik bayragi True olarak duzeltildi")
                self._phone_accessibility_enabled = True
            self._set_status(Ui.MSG_PAIRED_WS)
            self._set_remote_controls_enabled(True)
            return
        if self._phone_accessibility_enabled is False:
            self._set_status(Ui.MSG_PAIRED_A11Y_OFF)
            self._set_remote_controls_enabled(False)
            return
        self._set_status(Ui.MSG_PAIRED_WAIT_STREAM)
        self._set_remote_controls_enabled(False)

    def _sync_stream_aspect_fit(self, ew: int | None = None, eh: int | None = None) -> None:
        if not hasattr(self, "_stream_aspect_host"):
            return
        if ew is None or eh is None:
            ew, eh = self._screen.effective_frame_size()
        if ew > 0 and eh > 0:
            self._stream_aspect_host.set_stream_dimensions(ew, eh)

    def _note_stream_frame(self, w: int, h: int) -> None:
        ew, eh = self._screen.displayed_size_for_incoming(w, h)
        self._sync_stream_aspect_fit(ew, eh)
