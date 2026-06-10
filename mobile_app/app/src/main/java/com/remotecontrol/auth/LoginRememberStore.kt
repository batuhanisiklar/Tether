package com.remotecontrol.auth

import android.content.Context




class LoginRememberStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun remember(): Boolean = prefs.getBoolean(KEY_REMEMBER, false)

    fun email(): String = prefs.getString(KEY_EMAIL, "").orEmpty()

    fun save(remember: Boolean, email: String) {
        val e = prefs.edit()
        if (!remember) {
            e.remove(KEY_REMEMBER).remove(KEY_EMAIL).remove(KEY_PHONE_DIGITS).apply()
            return
        }
        e.putBoolean(KEY_REMEMBER, true)
            .putString(KEY_EMAIL, email.trim())
            .remove(KEY_PHONE_DIGITS)
            .apply()
    }

    companion object {
        private const val PREFS_NAME = "RemoteControlLoginRemember"
        private const val KEY_REMEMBER = "remember_login_fields"
        private const val KEY_EMAIL = "remembered_email"
        private const val KEY_PHONE_DIGITS = "remembered_phone_digits"
    }
}
