"""
Ekran görüntüsü ve pano mixin'i.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QFileDialog


class ScreenshotHandlersMixin:
    """Panoya kopyalama, PNG kaydetme, metin gönderme."""

    def _screenshot_to_clipboard(self) -> None:
        pm = self._screen.get_export_pixmap()
        if pm is None or pm.isNull():
            self._set_status("Kopyalanacak görüntü yok.", error=True)
            return
        QApplication.clipboard().setPixmap(pm)
        self._set_status(f"Panoya kopyalandı ({pm.width()}×{pm.height()}).")

    def _screenshot_save_png(self) -> None:
        pm = self._screen.get_export_pixmap()
        if pm is None or pm.isNull():
            self._set_status("Kaydedilecek görüntü yok.", error=True)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "PNG olarak kaydet", "remote_ekran.png", "PNG (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if pm.save(path, "PNG"):
            self._set_status(f"Kaydedildi: {path}")
        else:
            self._set_status("PNG kaydedilemedi.", error=True)

    def _send_clipboard_text_to_phone(self) -> None:
        if not self._connected:
            self._set_status("Önce oturum ile bağlanın.", error=True)
            return
        text = QApplication.clipboard().text()
        if not (text or "").strip():
            self._set_status("Pano boş.", error=True)
            return
        self._ws_client.send_paste_text(text)
        self._set_status(f"Pano metni gönderildi ({len(text)} karakter).")
