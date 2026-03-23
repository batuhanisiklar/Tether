package com.remotecontrol

import android.content.Context

class SessionStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun isLoggedIn(): Boolean = authToken().isNotBlank()

    fun authToken(): String = prefs.getString(KEY_TOKEN, "").orEmpty()

    fun username(): String = prefs.getString(KEY_USERNAME, "").orEmpty()

    fun userId(): Int = prefs.getInt(KEY_USER_ID, -1)

    fun save(session: AuthSession) {
        prefs.edit()
            .putString(KEY_TOKEN, session.token)
            .putInt(KEY_USER_ID, session.userId)
            .putString(KEY_USERNAME, session.username)
            .apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val PREFS_NAME = "RemoteControlSession"
        private const val KEY_TOKEN = "auth_token"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_USERNAME = "username"
    }
}
