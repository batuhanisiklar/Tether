package com.remotecontrol.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.content.ClipData
import android.content.ClipboardManager
import android.media.AudioManager
import android.view.KeyEvent
import android.os.SystemClock
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.*

class ControlReceiver : AccessibilityService() {

    companion object {
        private const val TAG = "ControlReceiver"

        // Singleton erişim — MainActivity'den komut göndermek için
        var instance: ControlReceiver? = null
            private set

        /** Sessize almadan önce STREAM_MUSIC seviyesi (geri yükleme için). */
        private var musicVolBeforeMute: Int = -1
        private const val VOLUME_UI_MIN_INTERVAL_MS = 700L
        private var lastVolumeUiShownAtMs: Long = 0L
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "AccessibilityService connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    /**
     * Ekrana dokunma (normalize koordinatlar: 0.0–1.0)
     */
    fun performTouch(normX: Float, normY: Float): Boolean {
        val display = getSystemService(Context.WINDOW_SERVICE) as android.view.WindowManager
        val metrics = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            display.currentWindowMetrics.bounds
        } else {
            @Suppress("DEPRECATION")
            val dm = android.util.DisplayMetrics()
            display.defaultDisplay.getRealMetrics(dm)
            android.graphics.Rect(0, 0, dm.widthPixels, dm.heightPixels)
        }

        val x = normX.coerceIn(0f, 1f) * metrics.width()
        val y = normY.coerceIn(0f, 1f) * metrics.height()

        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0L, 100L)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()

        val accepted = dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription) {
                Log.d(TAG, "Touch at ($x, $y)")
            }
            override fun onCancelled(gestureDescription: GestureDescription) {
                Log.w(TAG, "Touch cancelled")
            }
        }, null)
        if (!accepted) {
            Log.w(TAG, "Touch gesture dispatch reddedildi")
        }
        return accepted
    }

    /**
     * Kaydırma (swipe) — normalize koordinatlar
     */
    fun performSwipe(nx1: Float, ny1: Float, nx2: Float, ny2: Float): Boolean {
        val display = getSystemService(Context.WINDOW_SERVICE) as android.view.WindowManager
        val metrics = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            display.currentWindowMetrics.bounds
        } else {
            @Suppress("DEPRECATION")
            val dm = android.util.DisplayMetrics()
            display.defaultDisplay.getRealMetrics(dm)
            android.graphics.Rect(0, 0, dm.widthPixels, dm.heightPixels)
        }

        val w = metrics.width().toFloat()
        val h = metrics.height().toFloat()

        val path = Path().apply {
            moveTo(nx1.coerceIn(0f, 1f) * w, ny1.coerceIn(0f, 1f) * h)
            lineTo(nx2.coerceIn(0f, 1f) * w, ny2.coerceIn(0f, 1f) * h)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0L, 400L)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        val accepted = dispatchGesture(gesture, null, null)
        if (!accepted) {
            Log.w(TAG, "Swipe gesture dispatch reddedildi")
        }
        Log.d(TAG, "Swipe ($nx1,$ny1)->($nx2,$ny2)")
        return accepted
    }

    /**
     * Sistem tuşu (Back, Home, Recents, Volume, Power)
     */
    fun performKeyEvent(keyCode: Int): Boolean {
        val handled = when (keyCode) {
            KeyEvent.KEYCODE_BACK -> performGlobalAction(GLOBAL_ACTION_BACK)
            KeyEvent.KEYCODE_HOME -> performGlobalAction(GLOBAL_ACTION_HOME)
            KeyEvent.KEYCODE_APP_SWITCH -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            KeyEvent.KEYCODE_POWER -> performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN)
            KeyEvent.KEYCODE_VOLUME_UP -> adjustVolume(1)
            KeyEvent.KEYCODE_VOLUME_DOWN -> adjustVolume(-1)
            KeyEvent.KEYCODE_VOLUME_MUTE -> toggleStreamMute()
            else -> {
                Log.w(TAG, "Unhandled key: $keyCode")
                false
            }
        }
        Log.d(TAG, "Key event: $keyCode handled=$handled")
        return handled
    }

    private fun adjustVolume(direction: Int): Boolean {
        return performVolumeDelta(if (direction > 0) 1 else -1)
    }

    fun performVolumeDelta(delta: Int): Boolean {
        if (delta == 0) return true
        return try {
            val am = getSystemService(android.content.Context.AUDIO_SERVICE) as AudioManager
            val stream = AudioManager.STREAM_MUSIC
            val minV = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                am.getStreamMinVolume(stream)
            } else {
                0
            }
            val maxV = am.getStreamMaxVolume(stream)
            val current = am.getStreamVolume(stream)
            val target = (current + delta).coerceIn(minV, maxV)
            if (target != current) {
                am.setStreamVolume(stream, target, volumeUiFlags())
            }
            true
        } catch (e: Exception) {
            Log.w(TAG, "Volume delta adjust: $e")
            false
        }
    }

    private fun volumeUiFlags(): Int {
        val now = SystemClock.uptimeMillis()
        return if (now - lastVolumeUiShownAtMs >= VOLUME_UI_MIN_INTERVAL_MS) {
            lastVolumeUiShownAtMs = now
            AudioManager.FLAG_SHOW_UI
        } else {
            0
        }
    }

    /**
     * Medya sesini tamamen kes / önceki seviyeye döndür.
     * ADJUST_TOGGLE_MUTE birçok OEM'de güvenilir değil; setStreamVolume kullanıyoruz.
     */
    private fun toggleStreamMute(): Boolean {
        val am = getSystemService(android.content.Context.AUDIO_SERVICE) as AudioManager
        val stream = AudioManager.STREAM_MUSIC
        return try {
            val maxV = am.getStreamMaxVolume(stream)
            val cur = am.getStreamVolume(stream)
            when {
                cur > 0 -> {
                    musicVolBeforeMute = cur
                    am.setStreamVolume(stream, 0, volumeUiFlags())
                    Log.d(TAG, "Mute: volume 0 (was $cur)")
                }
                else -> {
                    val restore = when {
                        musicVolBeforeMute in 1..maxV -> musicVolBeforeMute
                        else -> maxOf(1, maxV / 4)
                    }
                    am.setStreamVolume(stream, restore, volumeUiFlags())
                    Log.d(TAG, "Mute off: restored to $restore")
                    musicVolBeforeMute = -1
                }
            }
            true
        } catch (e: Exception) {
            Log.w(TAG, "Mute toggle: $e")
            false
        }
    }

    /**
     * Masaüstünden gelen düz metni odaklı alana yazar veya panoya yapıştırır.
     */
    fun performPasteText(text: String): Boolean {
        val t = text.ifBlank { return false }
        val cm = getSystemService(android.content.Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("rpc", t))

        val root = rootInActiveWindow ?: run {
            Log.w(TAG, "paste_text: rootInActiveWindow null")
            return false
        }

        try {
            val focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            if (focused == null) {
                Log.w(TAG, "paste_text: odakli metin alani yok (metin cihaz panosunda)")
                return false
            }
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    val args = Bundle()
                    args.putCharSequence(
                        AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                        t,
                    )
                    if (focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                        Log.d(TAG, "paste_text: SET_TEXT ok (${t.length} chars)")
                        return true
                    }
                }
                if (focused.performAction(AccessibilityNodeInfo.ACTION_PASTE)) {
                    Log.d(TAG, "paste_text: PASTE ok")
                    return true
                }
            } finally {
                focused.recycle()
            }
        } finally {
            root.recycle()
        }
        Log.w(TAG, "paste_text: basarisiz")
        return false
    }
}
