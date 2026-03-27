package com.remotecontrol

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.os.Build
import android.util.Log
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import kotlinx.coroutines.*

/**
 * Kontrol Alıcısı
 * ================
 * Signaling üzerinden gelen touch/swipe/key komutlarını uygular.
 *
 * NOT: Touch simülasyonu için AccessibilityService gereklidir.
 * Kullanıcının Ayarlar > Erişilebilirlik bölümünden bu servisi aktif etmesi gerekir.
 * Manifeste AccessibilityService tanımlanmıştır.
 *
 * Alternatif: ADB'yi root olmadan kullanmak için geliştirici seçeneklerinden USB debug.
 */
class ControlReceiver : AccessibilityService() {

    companion object {
        private const val TAG = "ControlReceiver"

        // Singleton erişim — MainActivity'den komut göndermek için
        var instance: ControlReceiver? = null
            private set
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
            else -> {
                Log.w(TAG, "Unhandled key: $keyCode")
                false
            }
        }
        Log.d(TAG, "Key event: $keyCode handled=$handled")
        return handled
    }
}
