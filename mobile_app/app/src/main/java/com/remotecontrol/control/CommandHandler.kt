package com.remotecontrol.control

import android.util.Log

class CommandHandler(
    private val callbacks: Callbacks,
) {
    interface Callbacks {
        fun touch(x: Float, y: Float)
        fun swipe(x1: Float, y1: Float, x2: Float, y2: Float)
        fun keyEvent(keyCode: Int)
        fun rotateScreen(degrees: Int)
        fun startScreenCapture()
        fun startCamera(useFront: Boolean)
        fun stopCamera()
        fun pasteText(text: String)
    }

    fun handle(action: String, params: Map<String, Any>) {
        when (action) {
            "touch" -> {
                val x = (params["x"] as? Number)?.toFloat() ?: return
                val y = (params["y"] as? Number)?.toFloat() ?: return
                callbacks.touch(x, y)
            }
            "swipe" -> {
                val x1 = (params["x1"] as? Number)?.toFloat() ?: return
                val y1 = (params["y1"] as? Number)?.toFloat() ?: return
                val x2 = (params["x2"] as? Number)?.toFloat() ?: return
                val y2 = (params["y2"] as? Number)?.toFloat() ?: return
                callbacks.swipe(x1, y1, x2, y2)
            }
            "key_event" -> {
                val keyCode = (params["key_code"] as? Number)?.toInt() ?: return
                callbacks.keyEvent(keyCode)
            }
            "rotate_screen" -> {
                val degrees = normalizeRotationDegrees((params["degrees"] as? Number)?.toInt() ?: 0)
                callbacks.rotateScreen(degrees)
            }
            "screen_capture_on" -> callbacks.startScreenCapture()
            "camera_on" -> callbacks.startCamera(useFront = false)
            "camera_off" -> callbacks.stopCamera()
            "paste_text" -> {
                val raw = params["text"]
                val text = when (raw) {
                    is String -> raw
                    else -> raw?.toString() ?: ""
                }
                if (text.isBlank()) return
                callbacks.pasteText(text)
            }
            else -> Log.w(TAG, "Unknown command: $action")
        }
    }

    companion object {
        private const val TAG = "CommandHandler"

        fun normalizeRotationDegrees(degrees: Int): Int {
            val normalized = ((degrees % 360) + 360) % 360
            return ((normalized + 45) / 90 * 90) % 360
        }
    }
}
