package com.remotecontrol.device

import android.content.Context
import android.provider.Settings
import java.net.NetworkInterface
import java.util.Collections

/**
 * Cihaz tanıma: mümkünse MAC (12 hex), degilse aid: + ANDROID_ID.
 */
object HardwareFingerprint {

    fun macOrAndroidId(context: Context): String {
        val fromIface = macFromInterfaces()
        if (fromIface != null) return fromIface
        val aid = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID,
        ) ?: "unknown"
        return "aid:$aid".lowercase()
    }

    private fun macFromInterfaces(): String? {
        try {
            val ifs = Collections.list(NetworkInterface.getNetworkInterfaces())
            for (nif in ifs) {
                if (!nif.isUp || nif.isLoopback) continue
                val name = nif.name.lowercase()
                if (name == "lo" || name.startsWith("dummy")) continue
                val mac = nif.hardwareAddress ?: continue
                if (mac.isEmpty() || mac.all { it == 0.toByte() }) continue
                val hex = mac.joinToString("") { b -> "%02x".format(b) }
                if (hex.length == 12 && hex != "020000000000") return hex
            }
        } catch (_: Exception) {
        }
        return null
    }
}
