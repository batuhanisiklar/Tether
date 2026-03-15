package com.remotecontrol

import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

/**
 * Login Aktivitesi
 * ================
 * Uygulamanın başlangıç ekranı.
 * Doğru kimlik bilgileriyle giriş yapılınca MainActivity'ye geçiş sağlar.
 * SharedPreferences ile oturum durumu saklanır (uygulama kapatılınca da hatırlanır).
 *
 * Geçici kimlik bilgileri:
 *   Kullanıcı adı : admin
 *   Şifre         : 1234
 */
class LoginActivity : AppCompatActivity() {

    companion object {
        private const val PREFS_NAME   = "LoginPrefs"
        private const val KEY_LOGGED   = "is_logged_in"

        // Geçici hardcoded kimlik bilgileri — ileride DB ile değiştirilecek
        private const val VALID_USER   = "admin"
        private const val VALID_PASS   = "1234"
    }

    private lateinit var prefs: SharedPreferences

    private lateinit var etUsername  : EditText
    private lateinit var etPassword  : EditText
    private lateinit var btnLogin    : Button
    private lateinit var tvError     : TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)

        // Daha önce giriş yapıldıysa direkt MainActivity'ye geç
        if (prefs.getBoolean(KEY_LOGGED, false)) {
            goToMain()
            return
        }

        setContentView(R.layout.activity_login)
        bindViews()
    }

    private fun bindViews() {
        etUsername = findViewById(R.id.et_username)
        etPassword = findViewById(R.id.et_password)
        btnLogin   = findViewById(R.id.btn_login)
        tvError    = findViewById(R.id.tv_login_error)

        btnLogin.setOnClickListener { attemptLogin() }

        // Klavye "Done" tuşuyla da giriş yapılabilsin
        etPassword.setOnEditorActionListener { _, _, _ ->
            attemptLogin()
            true
        }
    }

    private fun attemptLogin() {
        val username = etUsername.text.toString().trim()
        val password = etPassword.text.toString()

        if (username.isEmpty() || password.isEmpty()) {
            showError("Lütfen tüm alanları doldurun.")
            return
        }

        if (username == VALID_USER && password == VALID_PASS) {
            // Oturumu kaydet
            prefs.edit().putBoolean(KEY_LOGGED, true).apply()
            hideError()
            goToMain()
        } else {
            showError("Kullanıcı adı veya şifre hatalı.")
            etPassword.text.clear()
            etPassword.requestFocus()
        }
    }

    private fun goToMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun showError(msg: String) {
        tvError.text = "⚠  $msg"
        tvError.visibility = View.VISIBLE
    }

    private fun hideError() {
        tvError.visibility = View.GONE
    }
}
