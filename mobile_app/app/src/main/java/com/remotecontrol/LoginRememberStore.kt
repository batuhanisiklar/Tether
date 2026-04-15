package com.remotecontrol

import android.content.Context

/**
 * Giriş ekranı: e-posta + telefon (rakam) hatırlama. Oturum token'ı burada tutulmaz.
 */
class LoginRememberStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun remember(): Boolean = prefs.getBoolean(KEY_REMEMBER, false)

    fun email(): String = prefs.getString(KEY_EMAIL, "").orEmpty()

    /** Sadece rakamlar (ör. 05321234567). */
    fun phoneDigits(): String = prefs.getString(KEY_PHONE_DIGITS, "").orEmpty()

    fun save(remember: Boolean, email: String, phoneDigits: String) {
        val e = prefs.edit()
        if (!remember) {
            e.remove(KEY_REMEMBER).remove(KEY_EMAIL).remove(KEY_PHONE_DIGITS).apply()
            return
        }
        e.putBoolean(KEY_REMEMBER, true)
            .putString(KEY_EMAIL, email.trim())
            .putString(KEY_PHONE_DIGITS, phoneDigits.filter { it.isDigit() }.take(11))
            .apply()
    }

    companion object {
        private const val PREFS_NAME = "RemoteControlLoginRemember"
        private const val KEY_REMEMBER = "remember_login_fields"
        private const val KEY_EMAIL = "remembered_email"
        private const val KEY_PHONE_DIGITS = "remembered_phone_digits"
    }
}
