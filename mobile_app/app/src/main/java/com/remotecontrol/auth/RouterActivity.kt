package com.remotecontrol.auth

import android.content.Intent
import android.os.Bundle
import android.app.Activity








class RouterActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }
}
