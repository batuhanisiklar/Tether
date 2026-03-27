package com.remotecontrol

import android.content.Context

class SessionStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun isLoggedIn(): Boolean = authToken().isNotBlank()

    fun authToken(): String = prefs.getString(KEY_TOKEN, "").orEmpty()

    fun username(): String = prefs.getString(KEY_USERNAME, "").orEmpty()

    fun address(): String = prefs.getString(KEY_ADDRESS, "").orEmpty()

    fun userId(): Int = prefs.getInt(KEY_USER_ID, -1)

    fun save(session: AuthSession) {
        prefs.edit()
            .putString(KEY_TOKEN, session.token)
            .putInt(KEY_USER_ID, session.userId)
            .putString(KEY_USERNAME, session.username)
            .putString(KEY_ADDRESS, session.address)
            .apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    fun pairedPcId(): String? = prefs.getString(KEY_PAIRED_PC_ID, null)

    fun savePairedPcId(deviceId: String) {
        prefs.edit().putString(KEY_PAIRED_PC_ID, deviceId).apply()
    }

    fun clearPairedPcId() {
        prefs.edit().remove(KEY_PAIRED_PC_ID).apply()
    }

    fun pairedPcAddress(): String? = prefs.getString(KEY_PAIRED_PC_ADDRESS, null)

    fun savePairedPcAddress(address: String) {
        val digits = address.filter(Char::isDigit).take(12)
        prefs.edit().putString(KEY_PAIRED_PC_ADDRESS, digits).apply()
    }

    fun clearPairedPcAddress() {
        prefs.edit().remove(KEY_PAIRED_PC_ADDRESS).apply()
    }

    companion object {
        private const val PREFS_NAME = "RemoteControlSession"
        private const val KEY_TOKEN = "auth_token"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_USERNAME = "username"
        private const val KEY_ADDRESS = "address"
        private const val KEY_PAIRED_PC_ID = "paired_pc_id"
        private const val KEY_PAIRED_PC_ADDRESS = "paired_pc_address"
    }
}
