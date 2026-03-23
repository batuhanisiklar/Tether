package com.remotecontrol

import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import com.remotecontrol.databinding.ActivityLoginBinding

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
    private lateinit var binding: ActivityLoginBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)

        // Daha önce giriş yapıldıysa direkt MainActivity'ye geç
        if (prefs.getBoolean(KEY_LOGGED, false)) {
            goToMain()
            return
        }

        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)
        bindViews()
    }

    private fun bindViews() {
        binding.btnLogin.setOnClickListener { attemptLogin() }

        // Klavye "Done" tuşuyla da giriş yapılabilsin
        binding.etPassword.setOnEditorActionListener { _, _, _ ->
            attemptLogin()
            true
        }
    }

    private fun attemptLogin() {
        val username = binding.etUsername.text.toString().trim()
        val password = binding.etPassword.text.toString()

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
            binding.etPassword.text.clear()
            binding.etPassword.requestFocus()
        }
    }

    private fun goToMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun showError(msg: String) {
        binding.tvLoginError.text = "⚠  $msg"
        binding.tvLoginError.visibility = View.VISIBLE
    }

    private fun hideError() {
        binding.tvLoginError.visibility = View.GONE
    }
}
