package com.remotecontrol.auth

import android.content.Intent
import android.os.Bundle
import android.text.method.HideReturnsTransformationMethod
import android.text.method.PasswordTransformationMethod
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.ImageButton
import androidx.appcompat.app.AppCompatActivity
import com.remotecontrol.R
import com.remotecontrol.data.BackendApi
import com.remotecontrol.data.DeviceIdentityStore
import com.remotecontrol.databinding.ActivityLoginBinding
import com.remotecontrol.device.HardwareFingerprint
import com.remotecontrol.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Giris: e-posta + sifre. Kayit: ek alanlar + opsiyonel telefon + sifre tekrar.
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
    private var validatingStoredSession = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        sessionStore = SessionStore(this)
        rememberStore = LoginRememberStore(this)
        deviceIdentityStore = DeviceIdentityStore(this)
        backendApi = BackendApi(MainActivity.SIGNALING_URL)

        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)
        bindViews()
        loadRememberedFields()
        applyAuthModeUi()

        if (sessionStore.isLoggedIn()) {
            showSessionValidation(true)
            validateExistingSession()
        }
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
        field: EditText,
        getVisible: () -> Boolean,
        setVisible: (Boolean) -> Unit,
    ) {
        fun applyUi() {
            val visible = getVisible()
            field.transformationMethod = if (visible) {
                HideReturnsTransformationMethod.getInstance()
            } else {
                PasswordTransformationMethod.getInstance()
            }
            field.setSelection(field.text.length)
            button.setImageResource(if (visible) R.drawable.ic_visibility_off else R.drawable.ic_visibility)
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
    }

    private fun phoneDigitsOnly(): String =
        binding.etPhone.text.toString().filter { it.isDigit() }

    private fun refreshPhoneBlockVisibility() {
        binding.phoneBlock.visibility = if (registerMode) View.VISIBLE else View.GONE
    }

    private fun applyAuthModeUi() {
        val register = registerMode
        binding.registerFieldsBlock.visibility = if (register) View.VISIBLE else View.GONE
        binding.passwordConfirmRow.visibility = if (register) View.VISIBLE else View.GONE
        binding.labelPasswordConfirm.visibility = if (register) View.VISIBLE else View.GONE
        binding.chkRemember.visibility = if (register) View.GONE else View.VISIBLE
        binding.btnLogin.text = getString(if (register) R.string.register_submit_button else R.string.login_button)
        binding.tvAuthSwitch.text = getString(
            if (register) R.string.login_switch_to_login else R.string.login_switch_to_register,
        )
        refreshPhoneBlockVisibility()
        resetPasswordVisibilityUi()
        hideError()
        syncSessionValidationUi()
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
            showError(getString(R.string.login_error_email_password_required))
            return
        }
        if (isRegister) {
            if (firstName.isEmpty() || lastName.isEmpty()) {
                showError(getString(R.string.login_error_name_required))
                return
            }
            if (!email.contains("@")) {
                showError(getString(R.string.login_error_email_invalid))
                return
            }
            if (password.length < 6) {
                showError(getString(R.string.login_error_password_short))
                return
            }
            if (password != password2) {
                showError(getString(R.string.login_error_password_mismatch))
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
                showError(result.error ?: getString(R.string.login_error_unexpected))
                if (!isRegister) {
                    binding.etPassword.text.clear()
                    binding.etPassword.requestFocus()
                }
                return@launch
            }

            if (isRegister) {
                rememberStore.save(true, email)
            } else {
                rememberStore.save(binding.chkRemember.isChecked, email)
            }

            sessionStore.save(result.data)
            val savedDeviceId = result.data.address.filter { it.isDigit() }.take(12).ifBlank { deviceIdentityStore.deviceId() }
            deviceIdentityStore.saveDeviceId(savedDeviceId)

            val profileRes = backendApi.getProfile(result.data.token, savedDeviceId)
            profileRes.data?.let { profile ->
                sessionStore.saveProfile(profile.firstName, profile.lastName, profile.email, profile.phone)
            }

            hideError()
            goToMain()
        }
    }

    private fun validateExistingSession() {
        validatingStoredSession = true
        syncSessionValidationUi()
        setLoading(true, isRegisterFlow = false)
        hideError()
        scope.launch {
            val token = sessionStore.authToken()
            val currentDeviceId = sessionStore.address()
                .filter { it.isDigit() }
                .take(12)
                .ifBlank { deviceIdentityStore.deviceId() }
            val result = backendApi.getMe(token, currentDeviceId)
            val session = result.data

            if (session != null) {
                sessionStore.save(session)
                val savedDeviceId = session.address
                    .filter { it.isDigit() }
                    .take(12)
                    .ifBlank { currentDeviceId }
                deviceIdentityStore.saveDeviceId(savedDeviceId)

                val profileRes = backendApi.getProfile(session.token, savedDeviceId)
                profileRes.data?.let { profile ->
                    sessionStore.saveProfile(profile.firstName, profile.lastName, profile.email, profile.phone)
                }
                goToMain()
                return@launch
            }

            validatingStoredSession = false
            syncSessionValidationUi()
            setLoading(false, isRegisterFlow = false)
            showError(result.error ?: getString(R.string.login_error_unexpected))
            if (result.statusCode in setOf(401, 403, 404)) {
                sessionStore.clear()
            }
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

    private fun showSessionValidation(show: Boolean) {
        validatingStoredSession = show
        syncSessionValidationUi()
    }

    private fun syncSessionValidationUi() {
        binding.layoutSessionValidation.visibility = if (validatingStoredSession) View.VISIBLE else View.GONE
        binding.loginFormScroll.visibility = if (validatingStoredSession) View.GONE else View.VISIBLE
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
