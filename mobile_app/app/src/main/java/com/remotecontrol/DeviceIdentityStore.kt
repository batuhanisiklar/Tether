package com.remotecontrol

import android.content.Context
import java.util.UUID
import kotlin.random.Random

class DeviceIdentityStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun deviceId(): String {
        return prefs.getString(KEY_DEVICE_ID, null)
            ?.takeIf { it.length == 12 && it.all(Char::isDigit) }
            ?: buildString {
                repeat(12) { append(Random.nextInt(10)) }
            }.let { newId ->
                prefs.edit().putString(KEY_DEVICE_ID, newId).apply()
                newId
            }
    }

    fun clearDeviceId() {
        prefs.edit().remove(KEY_DEVICE_ID).apply()
    }

    fun saveDeviceId(deviceId: String) {
        val normalized = deviceId.filter(Char::isDigit).take(12)
        if (normalized.length == 12) {
            prefs.edit().putString(KEY_DEVICE_ID, normalized).apply()
        }
    }

    companion object {
        private const val PREFS_NAME = "RemoteControlDevicePrefs"
        private const val KEY_DEVICE_ID = "device_id"
    }
}
