"""
Ana Pencere — Remote Phone Control
=====================================
Profesyonel koyu arayüz. Tüm renkler constants.Colors'dan alınır.
"""

import logging
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFrame, QStatusBar,
    QSplitter, QGroupBox, QGridLayout, QDialog,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QPixmap

from desktop_app.config import AppMeta, ServerDefaults, Network, Ui, Colors, AndroidKeyCodes
from desktop_app.ui.screen_widget import ScreenWidget
from desktop_app.network.ws_client import WsClient
from desktop_app.network.mjpeg_receiver import MjpegReceiver

logger = logging.getLogger(__name__)

# ── Buton renk stilleri (Colors'tan türetilir) ────────────────────────────────
def _btn_nav() -> str:
    return f"""
        QPushButton {{
            background-color: {Colors.BTN_NAV_BG};
            color: {Colors.BTN_NAV_FG};
            border: 1px solid {Colors.BTN_NAV_BDR};
            border-radius: 4px; padding: 8px 4px; font-size: 11px; font-weight: 500;
        }}
        QPushButton:hover  {{ background-color: #253060; border-color: {Colors.ACCENT}; color: {Colors.TEXT}; }}
        QPushButton:pressed {{ background-color: {Colors.ACCENT_DIM}; }}
        QPushButton:disabled {{ background-color: {Colors.BG_INPUT}; color: {Colors.TEXT_OFF}; border-color: {Colors.BORDER}; }}
    """

def _btn_vol() -> str:
    return f"""
        QPushButton {{
            background-color: {Colors.BTN_VOL_BG};
            color: {Colors.BTN_VOL_FG};
            border: 1px solid {Colors.BTN_VOL_BDR};
            border-radius: 4px; padding: 8px 4px; font-size: 11px; font-weight: 500;
        }}
        QPushButton:hover  {{ background-color: #253A25; border-color: {Colors.SUCCESS}; color: {Colors.TEXT}; }}
        QPushButton:pressed {{ background-color: #1A2A1A; }}
        QPushButton:disabled {{ background-color: {Colors.BG_INPUT}; color: {Colors.TEXT_OFF}; border-color: {Colors.BORDER}; }}
    """

def _btn_screen() -> str:
    return f"""
        QPushButton {{
            background-color: {Colors.BTN_SCR_BG};
            color: {Colors.BTN_SCR_FG};
            border: 1px solid {Colors.BTN_SCR_BDR};
            border-radius: 4px; padding: 8px 4px; font-size: 11px; font-weight: 500;
        }}
        QPushButton:hover  {{ background-color: #351E3D; border-color: #9B59B6; color: {Colors.TEXT}; }}
        QPushButton:pressed {{ background-color: #1E1028; }}
        QPushButton:disabled {{ background-color: {Colors.BG_INPUT}; color: {Colors.TEXT_OFF}; border-color: {Colors.BORDER}; }}
    """

_GROUP_STYLES = {"nav": _btn_nav, "vol": _btn_vol, "screen": _btn_screen}


class MainWindow(QMainWindow):
    """Ana uygulama penceresi — Professional Dark."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(AppMeta.WINDOW_TITLE)
        self.setMinimumSize(AppMeta.MIN_WIDTH, AppMeta.MIN_HEIGHT)
        self.resize(AppMeta.DEFAULT_WIDTH, AppMeta.DEFAULT_HEIGHT)

        self._ws_client = WsClient()
        self._mjpeg = MjpegReceiver()
        self._connected = False
        self._rotation_step = 0   # 0=0°, 1=90°, 2=180°, 3=270°

        self._setup_style()
        self._build_ui()
        self._connect_signals()

        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(Network.HEARTBEAT_INTERVAL_MS)
        self._heartbeat.timeout.connect(self._ws_client.send_heartbeat)

    # ─── STYLE ────────────────────────────────────────────────────────────────

    def _setup_style(self):
        c = Colors
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {c.BG_APP}; }}
            QWidget      {{ background-color: transparent; color: {c.TEXT};
                           font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }}
            QGroupBox {{
                background-color: {c.BG_CARD};
                border: 1px solid {c.BORDER};
                border-radius: 5px;
                margin-top: 12px;
                padding: 14px 10px 10px 10px;
                font-size: 10px; font-weight: 700; letter-spacing: 1px; color: {c.TEXT_SUBTLE};
                text-transform: uppercase;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 2px 6px;
                background-color: {c.BG_CARD};
            }}
            QLineEdit {{
                background-color: {c.BG_INPUT};
                border: 1px solid {c.BORDER_INPUT};
                border-radius: 4px; padding: 8px 12px;
                color: {c.TEXT}; font-size: 13px;
                selection-background-color: {c.ACCENT};
            }}
            QLineEdit:focus {{ border-color: {c.BORDER_FOCUS}; }}
            QPushButton {{ border: none; border-radius: 4px;
                          padding: 7px 12px; font-size: 12px; font-weight: 500; }}
            QPushButton#btn_connect {{
                background-color: {c.BTN_CONNECT_BG}; color: #FFFFFF;
            }}
            QPushButton#btn_connect:hover   {{ background-color: {c.BTN_CONNECT_HOV}; }}
            QPushButton#btn_connect:pressed {{ background-color: {c.BTN_CONNECT_PRESS}; }}
            QPushButton#btn_connect:disabled {{
                background-color: #1E3A2A; color: #3A6A4A;
                border: 1px solid #1E3A2A;
            }}
            QPushButton#btn_disconnect {{
                background-color: {c.BTN_DISCONNECT_BG};
                color: {c.BTN_DISCONNECT_FG};
                border: 1px solid {c.BTN_DISCONNECT_BDR};
            }}
            QPushButton#btn_disconnect:hover   {{ background-color: {c.BTN_DISCONNECT_HOV}; }}
            QPushButton#btn_disconnect:disabled {{
                background-color: {c.BG_INPUT}; color: {c.TEXT_OFF};
                border: 1px solid {c.BORDER};
            }}
            QPushButton#btn_rotate {{
                background-color: {c.BTN_NAV_BG};
                color: {c.BTN_NAV_FG};
                border: 1px solid {c.BTN_NAV_BDR};
            }}
            QPushButton#btn_rotate:hover   {{ background-color: #253060; color: {c.TEXT}; }}
            QPushButton#btn_rotate:disabled {{
                background-color: {c.BG_INPUT}; color: {c.TEXT_OFF}; border-color: {c.BORDER};
            }}
            QStatusBar {{
                background-color: {c.BG_APP}; color: {c.TEXT_MUTED};
                border-top: 1px solid {c.BORDER}; font-size: 11px; padding: 0 8px;
            }}
            QSplitter::handle {{ background-color: {c.BORDER}; width: 1px; }}
        """)

    # ─── UI BUILD ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background-color: {Colors.BG_APP};")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_screen_area())
        splitter.setSizes([Ui.SPLITTER_LEFT_SIZE, Ui.SPLITTER_RIGHT_SIZE])
        root.addWidget(splitter, stretch=1)

        self._status_bar = QStatusBar()
        self._status_bar.showMessage(Ui.MSG_WAITING)
        self.setStatusBar(self._status_bar)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setFixedHeight(Ui.HEADER_HEIGHT)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Remote Phone Control")
        title.setStyleSheet(
            f"color: {Colors.TEXT}; font-size: 14px; font-weight: 600;"
            f" letter-spacing: -0.2px; background: transparent;"
        )
        lay.addWidget(title)

        ver = QLabel(f"  v{AppMeta.VERSION}")
        ver.setStyleSheet(f"color: {Colors.TEXT_OFF}; font-size: 11px; background: transparent;")
        lay.addWidget(ver)
        lay.addStretch()

        # Bağlantı durumu
        self._status_indicator = QFrame()
        self._status_indicator.setFixedSize(8, 8)
        self._status_indicator.setStyleSheet(
            f"background-color: {Colors.TEXT_OFF}; border-radius: 4px;"
        )
        lay.addWidget(self._status_indicator)
        lay.addSpacing(6)

        self._lbl_status_text = QLabel("Bağlı Değil")
        self._lbl_status_text.setStyleSheet(
            f"color: {Colors.TEXT_OFF}; font-size: 12px; background: transparent;"
        )
        lay.addWidget(self._lbl_status_text)
        lay.addSpacing(20)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(20)
        sep.setStyleSheet(f"background-color: {Colors.BORDER}; max-width: 1px;")
        lay.addWidget(sep)
        lay.addSpacing(20)

        self._btn_logout = QPushButton("Oturumu Kapat")
        self._btn_logout.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {Colors.TEXT_MUTED};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px; padding: 4px 12px; font-size: 11px;
            }}
            QPushButton:hover {{
                color: {Colors.BTN_DANGER_FG};
                border-color: {Colors.BTN_DANGER_BDR};
                background-color: {Colors.BTN_DANGER_BG};
            }}
        """)
        self._btn_logout.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_logout.clicked.connect(self._on_logout)
        lay.addWidget(self._btn_logout)

        self._lbl_status_dot = QLabel()   # legacy compat
        self._lbl_status_dot.hide()
        return header

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(Ui.LEFT_PANEL_WIDTH)
        panel.setStyleSheet(
            f"background-color: {Colors.BG_SURFACE};"
            f" border-right: 1px solid {Colors.BORDER};"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # ── Bağlantı ─────────────────────────────────────────────────
        grp_conn = QGroupBox("Bağlantı")
        cl = QVBoxLayout(grp_conn)
        cl.setSpacing(7)

        cl.addWidget(self._lbl(f"Oturum Kodu  ({ServerDefaults.CODE_LENGTH} hane)"))
        self._inp_code = QLineEdit()
        self._inp_code.setPlaceholderText(Ui.PLACEHOLDER_CODE)
        self._inp_code.setMaxLength(ServerDefaults.CODE_LENGTH)
        self._inp_code.setFixedHeight(36)
        self._inp_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inp_code.setStyleSheet(f"""
            QLineEdit {{
                background-color: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER_INPUT};
                border-radius: 4px; padding: 0 12px;
                color: {Colors.TEXT}; font-size: 15px;
                font-family: 'Segoe UI', Arial, sans-serif;
                letter-spacing: 2px;
                selection-background-color: {Colors.ACCENT};
            }}
            QLineEdit:focus {{ border-color: {Colors.BORDER_FOCUS}; }}
        """)
        cl.addWidget(self._inp_code)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_connect = QPushButton("Bağlan")
        self._btn_connect.setObjectName("btn_connect")
        self._btn_connect.setFixedHeight(32)
        self._btn_connect.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BTN_CONNECT_BG};
                color: #FFFFFF; border: none; border-radius: 4px;
                font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover   {{ background-color: {Colors.BTN_CONNECT_HOV}; }}
            QPushButton:pressed {{ background-color: {Colors.BTN_CONNECT_PRESS}; }}
            QPushButton:disabled {{
                background-color: #243A2A; color: #3D6045; border: none;
            }}
        """)
        self._btn_disconnect = QPushButton("Bağlantıyı Kes")
        self._btn_disconnect.setObjectName("btn_disconnect")
        self._btn_disconnect.setFixedHeight(32)
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BTN_DISCONNECT_BG};
                color: {Colors.BTN_DISCONNECT_FG};
                border: 1px solid {Colors.BTN_DISCONNECT_BDR};
                border-radius: 4px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover   {{ background-color: {Colors.BTN_DISCONNECT_HOV}; }}
            QPushButton:disabled {{
                background-color: {Colors.BG_INPUT};
                color: {Colors.TEXT_OFF};
                border: 1px solid {Colors.BORDER};
            }}
        """)
        btn_row.addWidget(self._btn_connect)
        btn_row.addWidget(self._btn_disconnect)
        cl.addLayout(btn_row)
        lay.addWidget(grp_conn)

        # ── Ekran Kontrolü ───────────────────────────────────────────
        grp_screen = QGroupBox("Ekran")
        sl = QVBoxLayout(grp_screen)
        sl.setSpacing(6)

        self._btn_rotate = QPushButton("Yatay Moda Geç  ↻")
        self._btn_rotate.setObjectName("btn_rotate")
        self._btn_rotate.setFixedHeight(32)
        self._btn_rotate.setEnabled(False)
        self._btn_rotate.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_rotate.clicked.connect(self._on_rotate_toggle)
        sl.addWidget(self._btn_rotate)
        lay.addWidget(grp_screen)

        # ── Tuş Kontrolleri ─────────────────────────────────────────
        grp_keys = QGroupBox("Tuş Kontrolleri")
        kl = QGridLayout(grp_keys)
        kl.setSpacing(5)
        key_codes = AndroidKeyCodes.as_mapping()
        self._key_buttons = []

        for label, group, row, col, key_id in AndroidKeyCodes.button_specs():
            btn = QPushButton(label)
            btn.setStyleSheet(_GROUP_STYLES[group]())
            btn.clicked.connect(lambda _, k=key_codes[key_id]: self._ws_client.send_key_event(k))
            btn.setEnabled(False)
            self._key_buttons.append(btn)
            kl.addWidget(btn, row, col)
        lay.addWidget(grp_keys)

        # ── Nasıl Kullanılır ─────────────────────────────────────────
        grp_help = QGroupBox("Nasıl Bağlanılır")
        hl = QVBoxLayout(grp_help)
        for step in [
            "1.  Telefon uygulamasını açın",
            "2.  6 haneli kodu buraya girin",
            "3.  'Bağlan' butonuna tıklayın",
            "4.  Telefon ekranı sağda görünür",
        ]:
            lbl = QLabel(step)
            lbl.setStyleSheet(
                f"color: {Colors.TEXT_MUTED}; font-size: 11px; padding: 1px 0;"
                f" background: transparent;"
            )
            hl.addWidget(lbl)
        lay.addWidget(grp_help)

        lay.addStretch()
        return panel

    def _build_screen_area(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet(f"background-color: {Colors.BG_APP};")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        top_bar = QWidget()
        top_bar.setFixedHeight(32)
        top_bar.setStyleSheet(
            f"background-color: {Colors.BG_SURFACE};"
            f" border-bottom: 1px solid {Colors.BORDER};"
        )
        bar_lay = QHBoxLayout(top_bar)
        bar_lay.setContentsMargins(16, 0, 16, 0)

        screen_lbl = QLabel("EKRAN GÖRÜNTÜSÜ")
        screen_lbl.setStyleSheet(
            f"color: {Colors.TEXT_SUBTLE}; font-size: 10px; font-weight: 700;"
            f" letter-spacing: 1px; background: transparent;"
        )
        bar_lay.addWidget(screen_lbl)
        bar_lay.addStretch()

        self._lbl_coords = QLabel("")
        self._lbl_coords.setStyleSheet(
            f"color: {Colors.TEXT_OFF}; font-size: 10px;"
            f" font-family: 'Consolas', monospace; background: transparent;"
        )
        bar_lay.addWidget(self._lbl_coords)
        lay.addWidget(top_bar)

        self._screen = ScreenWidget()
        lay.addWidget(self._screen, stretch=1)
        return container

    # ─── SIGNAL CONNECTIONS ───────────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        self._ws_client.connected.connect(self._on_ws_connected)
        self._ws_client.disconnected.connect(self._on_ws_disconnected)
        self._ws_client.paired.connect(self._on_paired)
        self._ws_client.peer_disconnected.connect(self._on_peer_disconnected)
        self._ws_client.error_occurred.connect(self._on_error)
        self._ws_client.frame_received.connect(self._on_frame_received)
        self._mjpeg.frame_ready.connect(self._screen.set_frame)
        self._mjpeg.error_occurred.connect(self._on_mjpeg_error)
        self._mjpeg.stream_stopped.connect(self._on_stream_stopped)
        self._screen.touch_event.connect(self._on_touch)
        self._screen.swipe_event.connect(self._on_swipe)

    # ─── SLOTS ────────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_connect(self):
        code = self._inp_code.text().strip()
        if not code:
            self._set_status("Oturum kodu girilmedi.", error=True)
            return
        if len(code) != ServerDefaults.CODE_LENGTH or not code.isdigit():
            self._set_status(Ui.MSG_CODE_MUST_BE_6_DIGITS, error=True)
            return
        self._btn_connect.setEnabled(False)
        self._set_status(Ui.MSG_CONNECTING)
        self._ws_client.connect_to_server(ServerDefaults.DEFAULT_URL, code)

    @pyqtSlot()
    def _on_disconnect(self):
        self._mjpeg.stop()
        self._ws_client.disconnect()
        self._set_connected(False)
        self._screen.clear_frame()

    @pyqtSlot()
    def _on_logout(self):
        self._mjpeg.stop()
        self._ws_client.disconnect()
        import os, json
        try:
            with open(os.path.join(os.path.expanduser("~"), ".remote_control_prefs.json"), "w") as f:
                json.dump({"is_logged_in": False}, f)
        except Exception:
            pass
        from desktop_app.ui.login_window import LoginWindow
        if LoginWindow().exec() == QDialog.DialogCode.Accepted:
            self._set_status(Ui.MSG_WAITING)
        else:
            import sys; sys.exit(0)

    @pyqtSlot()
    def _on_ws_connected(self):
        self._set_status(Ui.MSG_SERVER_CONNECTED)
        self._btn_disconnect.setEnabled(True)

    @pyqtSlot(str)
    def _on_ws_disconnected(self, reason: str):
        self._set_connected(False)
        if "10060" in reason or "timed out" in reason.lower():
            self._set_status(Ui.MSG_DISCONNECT_TIMEOUT, error=True)
        else:
            self._set_status(f"Bağlantı kesildi  —  {reason}", error=True)
        self._btn_connect.setEnabled(True)
        self._screen.clear_frame()

    @pyqtSlot(str)
    def _on_paired(self, stream_url: str):
        self._set_connected(True)
        if stream_url and stream_url.startswith("http"):
            if "0.0.0.0" not in stream_url and "10.0.2." not in stream_url:
                try:
                    self._mjpeg.start(stream_url)
                    self._set_status("Bağlandı  —  Video akışı aktif")
                    return
                except Exception:
                    pass
        self._set_status(Ui.MSG_PAIRED_WS)

    @pyqtSlot()
    def _on_peer_disconnected(self):
        self._mjpeg.stop()
        self._screen.clear_frame()
        self._set_connected(False)
        self._set_status(Ui.MSG_PEER_DISCONNECTED, error=True)

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self._set_status(f"Hata: {msg}", error=True)

    @pyqtSlot(QPixmap)
    def _on_frame_received(self, pixmap: QPixmap):
        logger.debug(f"Frame: {pixmap.width()}x{pixmap.height()}")
        self._screen.set_frame(pixmap)

    @pyqtSlot(str)
    def _on_mjpeg_error(self, _: str):
        if self._connected:
            self._set_status(Ui.MSG_PAIRED_WS)

    @pyqtSlot()
    def _on_stream_stopped(self):
        if self._connected:
            self._set_status(Ui.MSG_PAIRED_WS)
        else:
            self._screen.clear_frame()
            self._set_status(Ui.MSG_STREAM_STOPPED, error=True)

    @pyqtSlot()
    def _on_rotate_toggle(self):
        """
        Desktop tarafında görüntüyü döndür (90° adımlarla).
        Aynı zamanda telefona bilgi gönderilir; orientation lock kapalıysa
        telefon da döner.
        """
        self._rotation_step = (self._rotation_step + 1) % 4
        deg = self._rotation_step * 90
        self._screen.set_rotation(deg)

        labels = {0: "Yatay Moda Geç  ↻", 90: "180° Döndür  ↻",
                  180: "270° Döndür  ↻", 270: "Dikey Moda Geç  ↻"}
        self._btn_rotate.setText(labels[deg])

        # Telefona da bildir (orientation lock kapalıysa fiziksel ekran döner)
        self._ws_client.send_rotate_screen(deg == 90 or deg == 270)
        self._set_status(f"Görüntü {deg}° döndürüldü")

    @pyqtSlot(float, float)
    def _on_touch(self, x: float, y: float):
        self._ws_client.send_touch(x, y)
        self._lbl_coords.setText(f"x={x:.3f}  y={y:.3f}")

    @pyqtSlot(float, float, float, float)
    def _on_swipe(self, x1, y1, x2, y2):
        self._ws_client.send_swipe(x1, y1, x2, y2)
        self._lbl_coords.setText(f"({x1:.2f},{y1:.2f}) → ({x2:.2f},{y2:.2f})")

    # ─── HELPERS ──────────────────────────────────────────────────────────────

    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {Colors.TEXT_MUTED}; font-size: 11px; font-weight: 600;"
            f" background: transparent;"
        )
        return l

    def _set_connected(self, connected: bool):
        self._connected = connected
        color = Colors.SUCCESS if connected else Colors.TEXT_OFF
        self._status_indicator.setStyleSheet(
            f"background-color: {color}; border-radius: 4px;"
        )
        self._lbl_status_text.setStyleSheet(
            f"color: {color}; font-size: 12px; background: transparent;"
        )
        self._lbl_status_text.setText("Bağlandı" if connected else "Bağlı Değil")

        for btn in self._key_buttons:
            btn.setEnabled(connected)
        self._btn_rotate.setEnabled(connected)
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)

        if connected:
            self._heartbeat.start()
        else:
            self._heartbeat.stop()

    def _set_status(self, msg: str, error: bool = False):
        color = Colors.ERROR if error else Colors.TEXT_MUTED
        self._status_bar.setStyleSheet(f"color: {color};")
        self._status_bar.showMessage(msg)

    def closeEvent(self, event):
        self._mjpeg.stop()
        self._ws_client.disconnect()
        super().closeEvent(event)
