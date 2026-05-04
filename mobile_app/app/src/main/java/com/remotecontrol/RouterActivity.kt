package com.remotecontrol

import android.content.Intent
import android.os.Bundle
import android.app.Activity

/**
 * Uygulama acilis yonlendiricisi.
 *
 * LoginActivity / MainActivity bazen setContentView cagirmadan finish() ettigi icin
 * bazi cihazlarda "bos ekran" flash'i gorunebiliyor. Bu aktivite NoDisplay tema ile
 * sadece dogru hedefe yonlendirir ve kendini kapatir.
 */
class RouterActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val session = SessionStore(this)
        val next = if (session.isLoggedIn()) MainActivity::class.java else LoginActivity::class.java
        startActivity(Intent(this, next))
        finish()
    }
}
