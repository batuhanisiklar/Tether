package com.remotecontrol.auth

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

        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }
}
