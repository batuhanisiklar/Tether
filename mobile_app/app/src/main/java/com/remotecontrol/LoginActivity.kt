package com.remotecontrol

import android.content.Intent
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import com.remotecontrol.databinding.ActivityLoginBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Login Aktivitesi
 * ================
 * Uygulamanin giris ve kayit ekranidir.
 * Basarili giriste backend token'i saklanir ve logout olana kadar korunur.
 */
class LoginActivity : AppCompatActivity() {
    private lateinit var binding: ActivityLoginBinding
    private lateinit var sessionStore: SessionStore
    private lateinit var deviceIdentityStore: DeviceIdentityStore
    private lateinit var backendApi: BackendApi
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        sessionStore = SessionStore(this)
        deviceIdentityStore = DeviceIdentityStore(this)
        backendApi = BackendApi(MainActivity.SIGNALING_URL)

        if (sessionStore.isLoggedIn()) {
            goToMain()
            return
        }

        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)
        bindViews()
    }

    private fun bindViews() {
        binding.btnLogin.setOnClickListener { attemptLogin() }
        binding.btnRegister.setOnClickListener { attemptRegister() }

        binding.etPassword.setOnEditorActionListener { _, _, _ ->
            attemptLogin()
            true
        }
    }

    private fun attemptLogin() {
        submitAuth(isRegister = false)
    }

    private fun attemptRegister() {
        submitAuth(isRegister = true)
    }

    private fun submitAuth(isRegister: Boolean) {
        val username = binding.etUsername.text.toString().trim()
        val password = binding.etPassword.text.toString()
        val deviceId = deviceIdentityStore.deviceId()

        if (username.isEmpty() || password.isEmpty()) {
            showError("Lutfen tum alanlari doldurun.")
            return
        }

        setLoading(true, isRegister)
        hideError()
        scope.launch {
            val result = if (isRegister) {
                backendApi.register(username, password, deviceId, "phone")
            } else {
                backendApi.login(username, password, deviceId, "phone")
            }
            setLoading(false, isRegister)

            if (result.error != null || result.data == null) {
                showError(result.error ?: "Beklenmeyen bir hata olustu.")
                if (!isRegister) {
                    binding.etPassword.text.clear()
                    binding.etPassword.requestFocus()
                }
                return@launch
            }

            sessionStore.save(result.data)
            hideError()
            goToMain()
        }
    }

    private fun goToMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun showError(msg: String) {
        binding.tvLoginError.text = msg
        binding.tvLoginError.visibility = View.VISIBLE
    }

    private fun hideError() {
        binding.tvLoginError.visibility = View.GONE
    }

    private fun setLoading(loading: Boolean, isRegister: Boolean) {
        binding.btnLogin.isEnabled = !loading
        binding.btnRegister.isEnabled = !loading
        binding.btnLogin.text = if (loading && !isRegister) "Giris yapiliyor..." else getString(R.string.login_button)
        binding.btnRegister.text = if (loading && isRegister) "Kayit olusturuluyor..." else getString(R.string.register_button)
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
