package com.remotecontrol

import android.content.Context

/**
 * Sunucunun bu profil + MAC icin atadigi 12 haneli sabit adres (device_id).
 * Deger her zaman login/register veya /devices/upsert yanitindan gelir; cikista silinmez.
 * Istemci tarafinda rastgele/ donanim hash id uretilmez — kaynak DB + MAC eslesmesidir.
 */
class DeviceIdentityStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    /** Kayitli sunucu adresi; yoksa bos (ilk giris oncesi). */
    fun deviceId(): String {
        return prefs.getString(KEY_DEVICE_ID, null)
            ?.takeIf { it.length == 12 && it.all(Char::isDigit) }
            .orEmpty()
    }

    fun saveDeviceId(deviceId: String) {
        val normalized = deviceId.filter(Char::isDigit).take(12)
        if (normalized.length == 12) {
            prefs.edit().putString(KEY_DEVICE_ID, normalized).apply()
        }
    }

    /** Fabrika sifirlama vb.; normal cikista cagrilmaz. */
    fun clearDeviceId() {
        prefs.edit().remove(KEY_DEVICE_ID).apply()
    }

    companion object {
        private const val PREFS_NAME = "RemoteControlDevicePrefs"
        private const val KEY_DEVICE_ID = "device_id"
    }
}
