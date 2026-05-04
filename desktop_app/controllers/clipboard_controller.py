from __future__ import annotations

from typing import Callable

from PyQt6.QtWidgets import QApplication, QFileDialog, QWidget


class ClipboardController:
    def __init__(self, parent: QWidget, status_callback: Callable[[str, bool], None]) -> None:
        self._parent = parent
        self._set_status = status_callback

    def screenshot_to_clipboard(self, screen) -> None:
        pm = screen.get_export_pixmap()
        if pm is None or pm.isNull():
            self._set_status("Kopyalanacak görüntü yok.", True)
            return
        QApplication.clipboard().setPixmap(pm)
        self._set_status(f"Panoya kopyalandı ({pm.width()}×{pm.height()}).", False)

    def save_screenshot_png(self, screen) -> None:
        pm = screen.get_export_pixmap()
        if pm is None or pm.isNull():
            self._set_status("Kaydedilecek görüntü yok.", True)
            return
        path, _ = QFileDialog.getSaveFileName(
            self._parent, "PNG olarak kaydet", "remote_ekran.png", "PNG (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if pm.save(path, "PNG"):
            self._set_status(f"Kaydedildi: {path}", False)
        else:
            self._set_status("PNG kaydedilemedi.", True)

    def send_clipboard_text_to_phone(self, *, connected: bool, ws_client) -> None:
        if not connected:
            self._set_status("Önce oturum ile bağlanın.", True)
            return
        text = QApplication.clipboard().text()
        if not (text or "").strip():
            self._set_status("Pano boş.", True)
            return
        ws_client.send_paste_text(text)
        self._set_status(f"Pano metni gönderildi ({len(text)} karakter).", False)
