from __future__ import annotations

import logging
import threading
import time

from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

logger = logging.getLogger(__name__)

_MUTE_TOGGLE_COOLDOWN_S = 0.25 
_VOLUME_OP_COOLDOWN_S   = 0.05   


class AudioJitterBuffer:

    def __init__(self, pre_buffer_ms: int = 100, sample_rate: int = 16000, channels: int = 1, sample_bytes: int = 2):
        self._pre_buffer_bytes = int(sample_rate * channels * sample_bytes * (pre_buffer_ms / 1000))
        self._buffer = bytearray()
        self._started = False

    def push(self, pcm: bytes) -> bytes | None:
        self._buffer.extend(pcm)
        if not self._started:
            if len(self._buffer) >= self._pre_buffer_bytes:
                self._started = True
                chunk = bytes(self._buffer)
                self._buffer.clear()
                return chunk
            return None
        chunk = bytes(self._buffer)
        self._buffer.clear()
        return chunk

    def reset(self) -> None:
        self._buffer.clear()
        self._started = False


class DesktopAudioPlayer:

    def __init__(self, parent=None, sample_rate: int = 16000) -> None:
        self._audio_sink: QAudioSink | None = None
        self._audio_device = None
        self._last_volume = 1.0
        self._remote_muted = False
        self._jitter = AudioJitterBuffer(pre_buffer_ms=60, sample_rate=sample_rate)
        self._lock = threading.Lock()
        self._last_mute_toggle_t: float = 0.0
        self._last_volume_op_t: float = 0.0
        self._init_audio_player(parent, sample_rate)

    def _init_audio_player(self, parent, sample_rate: int) -> None:
        try:
            audio_format = QAudioFormat()
            audio_format.setSampleRate(sample_rate)
            audio_format.setChannelCount(1)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)

            default_device = QMediaDevices.defaultAudioOutput()
            if not default_device.isNull():
                self._audio_sink = QAudioSink(default_device, audio_format, parent)
                self._audio_device = self._audio_sink.start()
            else:
                logger.warning("No default audio output device found.")
        except Exception as exc:
            logger.error("Audio player başlatılamadı: %s", exc, exc_info=True)

    def write_pcm(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        with self._lock:
            if self._remote_muted:
                return
            chunk = self._jitter.push(pcm_bytes)
            if chunk is None or self._audio_device is None or self._audio_sink is None:
                return
            if self._audio_sink.state() == QAudio.State.StoppedState:
                self._audio_device = self._audio_sink.start()
            try:
                self._audio_device.write(chunk)
            except Exception:
                logger.debug("Audio chunk write failed", exc_info=True)

    def adjust_for_android_key(self, key_code: int, *, volume_up: int, volume_down: int, volume_mute: int) -> None:
        with self._lock:
            if self._audio_sink is None:
                return
            now = time.monotonic()

            if key_code == volume_mute:
                if now - self._last_mute_toggle_t < _MUTE_TOGGLE_COOLDOWN_S:
                    return
                self._last_mute_toggle_t = now

                current_vol = self._audio_sink.volume()
                if current_vol > 0.0:
                    self._last_volume = current_vol
                    self._audio_sink.setVolume(0.0)
                else:
                    self._audio_sink.setVolume(max(0.1, self._last_volume))
                return

            if now - self._last_volume_op_t < _VOLUME_OP_COOLDOWN_S:
                return
            self._last_volume_op_t = now

            current_vol = self._audio_sink.volume()
            if key_code == volume_up:
                self._audio_sink.setVolume(min(1.0, current_vol + 0.1))
            elif key_code == volume_down:
                self._audio_sink.setVolume(max(0.0, current_vol - 0.1))

    def set_remote_muted(self, muted: bool) -> None:
        with self._lock:
            prev = self._remote_muted
            self._remote_muted = bool(muted)

            if self._remote_muted and not prev:
                self._jitter.reset()

            if self._audio_sink is None:
                return

            if self._remote_muted:
                current = self._audio_sink.volume()
                if current > 0.0:
                    self._last_volume = current
                self._audio_sink.setVolume(0.0)
                return

            target = self._last_volume if self._last_volume > 0.0 else 1.0
            self._audio_sink.setVolume(min(1.0, max(0.05, target)))

    def reset(self) -> None:
        with self._lock:
            self._jitter.reset()
