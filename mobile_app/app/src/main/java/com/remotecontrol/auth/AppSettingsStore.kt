package com.remotecontrol.auth

import android.content.Context

class AppSettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun notifyOnConnect(): Boolean = prefs.getBoolean(KEY_NOTIFY_ON_CONNECT, true)

    fun notifyOnDisconnect(): Boolean = prefs.getBoolean(KEY_NOTIFY_ON_DISCONNECT, true)

    fun setNotifyOnConnect(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_NOTIFY_ON_CONNECT, enabled).apply()
    }

    fun setNotifyOnDisconnect(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_NOTIFY_ON_DISCONNECT, enabled).apply()
    }

    companion object {
        private const val PREFS_NAME = "RemoteControlSettings"
        private const val KEY_NOTIFY_ON_CONNECT = "notify_on_connect"
        private const val KEY_NOTIFY_ON_DISCONNECT = "notify_on_disconnect"
    }
}

