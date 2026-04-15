package com.remotecontrol

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.text.method.HideReturnsTransformationMethod
import android.text.method.PasswordTransformationMethod
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.ImageButton
import androidx.appcompat.app.AppCompatActivity
import com.remotecontrol.databinding.ActivityLoginBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Giriş: e-posta + şifre. Kayıt: ek alanlar + şifre tekrar (metin bağlantısı ile geçiş).
 */
class LoginActivity : AppCompatActivity() {
    private lateinit var binding: ActivityLoginBinding
    private lateinit var sessionStore: SessionStore
    private lateinit var rememberStore: LoginRememberStore
    private lateinit var deviceIdentityStore: DeviceIdentityStore
    private lateinit var backendApi: BackendApi
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private var registerMode = false

    private var loginPasswordVisible = false
    private var confirmPasswordVisible = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        sessionStore = SessionStore(this)
        rememberStore = LoginRememberStore(this)
        deviceIdentityStore = DeviceIdentityStore(this)
        backendApi = BackendApi(MainActivity.SIGNALING_URL)

        if (sessionStore.isLoggedIn()) {
            goToMain()
            return
        }

        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)
        attachPhoneFormatter()
        bindViews()
        loadRememberedFields()
        applyAuthModeUi()
    }

    private fun bindViews() {
        binding.btnLogin.setOnClickListener {
            if (registerMode) attemptRegister() else attemptLogin()
        }
        binding.tvAuthSwitch.setOnClickListener {
            registerMode = !registerMode
            applyAuthModeUi()
        }
        binding.etPassword.setOnEditorActionListener { _, actionId, _ ->
            if (!registerMode && (actionId == EditorInfo.IME_ACTION_DONE || actionId == EditorInfo.IME_ACTION_GO || actionId == EditorInfo.IME_ACTION_SEND)) {
                attemptLogin()
                return@setOnEditorActionListener true
            }
            false
        }
        binding.etPasswordConfirm.setOnEditorActionListener { _, actionId, _ ->
            if (registerMode && (actionId == EditorInfo.IME_ACTION_DONE || actionId == EditorInfo.IME_ACTION_GO)) {
                attemptRegister()
                return@setOnEditorActionListener true
            }
            false
        }
        wirePasswordToggle(
            binding.btnTogglePassword,
            binding.etPassword,
            getVisible = { loginPasswordVisible },
            setVisible = { loginPasswordVisible = it },
        )
        wirePasswordToggle(
            binding.btnTogglePasswordConfirm,
            binding.etPasswordConfirm,
            getVisible = { confirmPasswordVisible },
            setVisible = { confirmPasswordVisible = it },
        )
    }

    private fun wirePasswordToggle(
        button: ImageButton,
        field: android.widget.EditText,
        getVisible: () -> Boolean,
        setVisible: (Boolean) -> Unit,
    ) {
        fun applyUi() {
            val vis = getVisible()
            field.transformationMethod = if (vis) {
                HideReturnsTransformationMethod.getInstance()
            } else {
                PasswordTransformationMethod.getInstance()
            }
            field.setSelection(field.text.length)
            button.setImageResource(if (vis) R.drawable.ic_visibility_off else R.drawable.ic_visibility)
        }
        button.setOnClickListener {
            setVisible(!getVisible())
            applyUi()
        }
        applyUi()
    }

    private fun loadRememberedFields() {
        if (!rememberStore.remember()) return
        binding.chkRemember.isChecked = true
        if (rememberStore.email().isNotEmpty()) {
            binding.etEmail.setText(rememberStore.email())
        }
        val pd = rememberStore.phoneDigits()
        if (pd.isNotEmpty()) {
            binding.etPhone.setText(formatPhoneDisplay(pd))
        }
    }

    /**
     * Görünüm: 0(312) 456 78 90 — en fazla 11 rakam. API'ye yalnızca rakamlar gider.
     */
    private fun attachPhoneFormatter() {
        var selfChange = false
        binding.etPhone.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                if (selfChange) return
                val digits = s?.toString()?.filter { it.isDigit() }?.take(11) ?: ""
                val formatted = formatPhoneDisplay(digits)
                if (formatted != s.toString()) {
                    selfChange = true
                    binding.etPhone.setText(formatted)
                    binding.etPhone.setSelection(formatted.length)
                    selfChange = false
                }
            }
            override fun afterTextChanged(s: Editable?) {}
        })
    }

    private fun formatPhoneDisplay(d: String): String {
        if (d.isEmpty()) return ""
        val sb = StringBuilder()
        sb.append(d[0])
        if (d.length >= 2) {
            sb.append("(")
            sb.append(d.substring(1, minOf(4, d.length)))
            if (d.length >= 4) {
                sb.append(") ")
                sb.append(d.substring(4, minOf(7, d.length)))
            }
        }
        if (d.length >= 7) {
            sb.append(" ")
            sb.append(d.substring(7, minOf(9, d.length)))
        }
        if (d.length >= 9) {
            sb.append(" ")
            sb.append(d.substring(9, minOf(11, d.length)))
        }
        return sb.toString()
    }

    private fun phoneDigitsOnly(): String =
        binding.etPhone.text.toString().filter { it.isDigit() }

    private fun refreshPhoneBlockVisibility() {
        val reg = registerMode
        val rememberedPhone = rememberStore.remember() && rememberStore.phoneDigits().isNotEmpty()
        binding.phoneBlock.visibility = if (reg || rememberedPhone) View.VISIBLE else View.GONE
    }

    private fun applyAuthModeUi() {
        val reg = registerMode
        binding.registerFieldsBlock.visibility = if (reg) View.VISIBLE else View.GONE
        binding.passwordConfirmRow.visibility = if (reg) View.VISIBLE else View.GONE
        binding.labelPasswordConfirm.visibility = if (reg) View.VISIBLE else View.GONE
        binding.chkRemember.visibility = if (reg) View.GONE else View.VISIBLE
        binding.btnLogin.text = getString(if (reg) R.string.register_submit_button else R.string.login_button)
        binding.tvAuthSwitch.text = getString(
            if (reg) R.string.login_switch_to_login else R.string.login_switch_to_register,
        )
        refreshPhoneBlockVisibility()
        resetPasswordVisibilityUi()
        hideError()
    }

    private fun resetPasswordVisibilityUi() {
        loginPasswordVisible = false
        confirmPasswordVisible = false
        binding.etPassword.transformationMethod = PasswordTransformationMethod.getInstance()
        binding.etPasswordConfirm.transformationMethod = PasswordTransformationMethod.getInstance()
        binding.btnTogglePassword.setImageResource(R.drawable.ic_visibility)
        binding.btnTogglePasswordConfirm.setImageResource(R.drawable.ic_visibility)
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
        val phone = phoneDigitsOnly()
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

            if (isRegister) {
                rememberStore.save(true, email, phone)
            } else {
                rememberStore.save(binding.chkRemember.isChecked, email, phone)
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
        binding.tvAuthSwitch.isEnabled = !loading
        binding.chkRemember.isEnabled = !loading
        binding.btnLogin.text = when {
            loading && registerMode -> getString(R.string.register_loading)
            loading && !isRegisterFlow -> getString(R.string.login_loading)
            registerMode -> getString(R.string.register_submit_button)
            else -> getString(R.string.login_button)
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
