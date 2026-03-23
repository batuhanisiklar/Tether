package com.remotecontrol

import android.content.Context
import java.util.UUID

class DeviceIdentityStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun deviceId(): String {
        return prefs.getString(KEY_DEVICE_ID, null)
            ?: UUID.randomUUID().toString().replace("-", "").take(16).let { newId ->
                val phoneId = "phone-$newId"
                prefs.edit().putString(KEY_DEVICE_ID, phoneId).apply()
                phoneId
            }
    }

    fun pairedPcId(): String? = prefs.getString(KEY_PAIRED_PC_ID, null)

    fun savePairedPcId(deviceId: String) {
        prefs.edit().putString(KEY_PAIRED_PC_ID, deviceId).apply()
    }

    companion object {
        private const val PREFS_NAME = "RemoteControlDevicePrefs"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_PAIRED_PC_ID = "paired_pc_id"
    }
}
