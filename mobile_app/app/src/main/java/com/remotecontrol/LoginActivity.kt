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
 * Giris: e-posta + sifre. Kayit: ek alanlar + sifre tekrar (toggle ile).
 */
class LoginActivity : AppCompatActivity() {
    private lateinit var binding: ActivityLoginBinding
    private lateinit var sessionStore: SessionStore
    private lateinit var deviceIdentityStore: DeviceIdentityStore
    private lateinit var backendApi: BackendApi
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private var registerMode = false

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
        applyAuthModeUi()
    }

    private fun bindViews() {
        binding.btnLogin.setOnClickListener { attemptLogin() }
        binding.btnRegister.setOnClickListener {
            if (registerMode) attemptRegister() else {
                registerMode = true
                applyAuthModeUi()
            }
        }
        binding.tvAuthSwitch.setOnClickListener {
            registerMode = !registerMode
            applyAuthModeUi()
        }
        binding.etPassword.setOnEditorActionListener { _, _, _ ->
            if (!registerMode) attemptLogin()
            true
        }
    }

    private fun applyAuthModeUi() {
        val reg = registerMode
        binding.registerFieldsBlock.visibility = if (reg) View.VISIBLE else View.GONE
        binding.etPasswordConfirm.visibility = if (reg) View.VISIBLE else View.GONE
        binding.labelPasswordConfirm.visibility = if (reg) View.VISIBLE else View.GONE
        binding.btnLogin.visibility = if (reg) View.GONE else View.VISIBLE
        binding.btnRegister.text = getString(if (reg) R.string.register_submit_button else R.string.register_button)
        binding.tvAuthSwitch.text = getString(
            if (reg) R.string.login_switch_to_login else R.string.login_switch_to_register,
        )
        hideError()
    }

    private fun attemptLogin() {
        submitAuth(isRegister = false)
    }

    private fun attemptRegister() {
        submitAuth(isRegister = true)
    }

    private fun submitAuth(isRegister: Boolean) {
        val firstName = binding.etFirstName.text.toString().trim()
        val lastName = binding.etLastName.text.toString().trim()
        val email = binding.etEmail.text.toString().trim()
        val phone = binding.etPhone.text.toString().trim()
        val password = binding.etPassword.text.toString()
        val password2 = binding.etPasswordConfirm.text.toString()
        val deviceId = deviceIdentityStore.deviceId()
        val deviceName = MainActivity.buildDeviceName()
        val macFp = HardwareFingerprint.macOrAndroidId(this)

        if (email.isEmpty() || password.isEmpty()) {
            showError("E-posta ve sifre zorunludur.")
            return
        }
        if (isRegister) {
            if (firstName.isEmpty() || lastName.isEmpty()) {
                showError("Ad ve soyad zorunludur.")
                return
            }
            if (!email.contains("@")) {
                showError("Gecerli bir e-posta girin.")
                return
            }
            if (password.length < 6) {
                showError("Sifre en az 6 karakter olmali.")
                return
            }
            if (password != password2) {
                showError("Sifreler eslesmiyor.")
                return
            }
        }

        setLoading(true, isRegister)
        hideError()
        scope.launch {
            val result = if (isRegister) {
                backendApi.register(
                    firstName,
                    lastName,
                    email,
                    phone,
                    password,
                    deviceId,
                    "phone",
                    deviceName,
                    macFp,
                )
            } else {
                backendApi.login(email, password, deviceId, "phone", deviceName, macFp)
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
            deviceIdentityStore.saveDeviceId(result.data.address)
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

    private fun setLoading(loading: Boolean, isRegisterFlow: Boolean) {
        binding.btnLogin.isEnabled = !loading
        binding.btnRegister.isEnabled = !loading
        binding.tvAuthSwitch.isEnabled = !loading
        if (registerMode) {
            binding.btnRegister.text = when {
                loading -> getString(R.string.register_loading)
                else -> getString(R.string.register_submit_button)
            }
        } else {
            binding.btnLogin.text = when {
                loading && !isRegisterFlow -> getString(R.string.login_loading)
                else -> getString(R.string.login_button)
            }
            binding.btnRegister.text = getString(R.string.register_button)
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
