package com.remotecontrol.ui

import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.remotecontrol.R
import com.remotecontrol.data.ApiResult
import com.remotecontrol.data.AuthSession
import com.remotecontrol.data.UserProfile
import com.remotecontrol.databinding.FragmentSettingsBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Locale

class SettingsFragment : Fragment(), DashboardFragment {
    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private enum class AccountMode {
        ACTIONS,
        CHANGE_EMAIL,
        CHANGE_PHONE,
        CHANGE_PASSWORD,
        DELETE_ACCOUNT,
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentSettingsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        binding.btnLogout.setOnClickListener { (activity as? MainActivity)?.logout() }
        binding.btnProfileClearConnections.setOnClickListener { confirmClearConnections() }

        binding.switchNotifyConnect.setOnCheckedChangeListener { _, isChecked ->
            (activity as? MainActivity)?.appSettingsStoreRef()?.setNotifyOnConnect(isChecked)
        }
        binding.switchNotifyDisconnect.setOnCheckedChangeListener { _, isChecked ->
            (activity as? MainActivity)?.appSettingsStoreRef()?.setNotifyOnDisconnect(isChecked)
        }

        binding.btnChangeEmail.setOnClickListener { setAccountMode(AccountMode.CHANGE_EMAIL) }
        binding.btnChangePhone.setOnClickListener { setAccountMode(AccountMode.CHANGE_PHONE) }
        binding.btnProfileChangePassword.setOnClickListener { setAccountMode(AccountMode.CHANGE_PASSWORD) }
        binding.btnDeleteAccount.setOnClickListener { setAccountMode(AccountMode.DELETE_ACCOUNT) }

        binding.btnChangeEmailCancel.setOnClickListener { setAccountMode(AccountMode.ACTIONS) }
        binding.btnChangePhoneCancel.setOnClickListener { setAccountMode(AccountMode.ACTIONS) }
        binding.btnChangePasswordCancel.setOnClickListener { setAccountMode(AccountMode.ACTIONS) }
        binding.btnDeleteAccountCancel.setOnClickListener { setAccountMode(AccountMode.ACTIONS) }

        binding.btnChangeEmailSave.setOnClickListener { saveEmailInline() }
        binding.btnChangePhoneSave.setOnClickListener { savePhoneInline() }
        binding.btnChangePasswordSave.setOnClickListener { savePasswordInline() }
        binding.btnDeleteAccountConfirmInline.setOnClickListener { deleteAccountInline() }

        refreshContent()
        loadProfileIntoForm()
        loadNotificationSettings()
        bindAppInfo()
        setAccountMode(AccountMode.ACTIONS)
    }

    override fun onResume() {
        super.onResume()
        refreshContent()
    }

    override fun refreshContent() {
        val host = activity as? MainActivity ?: return
        binding.tvUsername.text = host.fullNameText()
        binding.tvProfileEmail.text = host.sessionStoreRef().email().ifBlank { "-" }
        binding.tvProfilePhone.text = host.sessionStoreRef().phone().trim().ifBlank { "-" }
        updateAvatarFromSession(host)
        loadNotificationSettings()
        bindAppInfo()
    }

    private fun updateAvatarFromSession(host: MainActivity) {
        val first = host.sessionStoreRef().firstName().trim()
        val last = host.sessionStoreRef().lastName().trim()
        val email = host.sessionStoreRef().email().trim()
        val a = first.firstOrNull()?.uppercaseChar()
        val b = last.firstOrNull()?.uppercaseChar()
        binding.tvProfileAvatar.text = when {
            a != null && b != null -> "$a$b"
            a != null -> "$a"
            email.isNotBlank() -> email.first().uppercaseChar().toString()
            else -> "?"
        }
    }

    private fun loadProfileIntoForm() {
        val host = activity as? MainActivity ?: return
        val token = host.sessionStoreRef().authToken()
        if (token.isBlank()) return
        binding.tvProfileHeaderError.visibility = View.GONE
        scope.launch {
            val result = fetchProfileWithRetry(host, token, host.currentDeviceId())
            if (!result.error.isNullOrBlank()) {
                binding.tvProfileHeaderError.text = result.error
                binding.tvProfileHeaderError.visibility = View.VISIBLE
                return@launch
            }
            val p = result.data ?: return@launch
            host.sessionStoreRef().saveProfile(p.firstName, p.lastName, p.email, p.phone)
            refreshContent()
            prepareAccountPanels()
        }
    }

    private suspend fun fetchProfileWithRetry(
        host: MainActivity,
        token: String,
        deviceId: String,
    ): ApiResult<UserProfile> {
        var last: ApiResult<UserProfile> = ApiResult(error = getString(R.string.settings_profile_fetch_failed))
        repeat(3) { attempt ->
            val result = host.backendApiRef().getProfile(token, deviceId)
            if (result.data != null) return result
            last = result
            if (attempt < 2) delay(400L * (attempt + 1))
        }
        return last
    }

    private fun setAccountMode(mode: AccountMode) {
        val showActions = mode == AccountMode.ACTIONS
        binding.tvAccountSettingsTitle.visibility = if (showActions) View.VISIBLE else View.GONE
        binding.tvAccountSettingsSubtitle.visibility = if (showActions) View.VISIBLE else View.GONE
        binding.layoutAccountActions.visibility = if (showActions) View.VISIBLE else View.GONE
        binding.layoutChangeEmailPanel.visibility = if (mode == AccountMode.CHANGE_EMAIL) View.VISIBLE else View.GONE
        binding.layoutChangePhonePanel.visibility = if (mode == AccountMode.CHANGE_PHONE) View.VISIBLE else View.GONE
        binding.layoutChangePasswordPanel.visibility = if (mode == AccountMode.CHANGE_PASSWORD) View.VISIBLE else View.GONE
        binding.layoutDeleteAccountPanel.visibility = if (mode == AccountMode.DELETE_ACCOUNT) View.VISIBLE else View.GONE
        if (!showActions) prepareAccountPanels()
    }

    private fun prepareAccountPanels() {
        val host = activity as? MainActivity ?: return
        val session = host.sessionStoreRef()
        binding.etChangeEmail.setText(session.email())
        binding.tvChangeEmailError.visibility = View.GONE

        binding.etChangePhone.setText(session.phone())
        binding.tvChangePhoneError.visibility = View.GONE

        binding.etChangePasswordOld.text?.clear()
        binding.etChangePasswordNew1.text?.clear()
        binding.etChangePasswordNew2.text?.clear()
        binding.tvChangePasswordError.visibility = View.GONE

        val sessionEmail = session.email().trim().lowercase(Locale.ROOT)
        binding.tvDeleteAccountInfo.text = getString(R.string.settings_delete_account_dialog_text, sessionEmail)
        binding.etDeleteAccountEmailInline.text?.clear()
        binding.etDeleteAccountPasswordInline.text?.clear()
        binding.tvDeleteAccountError.visibility = View.GONE
        setDeleteButtonBusy(false)
    }

    private fun saveEmailInline() {
        val host = activity as? MainActivity ?: return
        val session = host.sessionStoreRef()
        val token = session.authToken()
        if (token.isBlank()) return

        val newEmail = binding.etChangeEmail.text.toString().trim().lowercase(Locale.ROOT)
        binding.tvChangeEmailError.visibility = View.GONE
        if (newEmail.isBlank() || !newEmail.contains("@")) {
            binding.tvChangeEmailError.text = getString(R.string.settings_change_email_invalid)
            binding.tvChangeEmailError.visibility = View.VISIBLE
            return
        }

        scope.launch {
            val result = host.backendApiRef().updateProfile(
                token = token,
                email = newEmail,
                phone = session.phone(),
                oldPassword = "",
                password = "",
                password2 = "",
            )
            if (!result.error.isNullOrBlank()) {
                binding.tvChangeEmailError.text = result.error
                binding.tvChangeEmailError.visibility = View.VISIBLE
                return@launch
            }
            val updated = result.data ?: return@launch
            val address = session.address()
            session.save(AuthSession(updated.token, updated.userId, updated.username, address))
            session.saveProfile(session.firstName(), session.lastName(), newEmail, session.phone())
            Toast.makeText(requireContext(), getString(R.string.settings_email_updated), Toast.LENGTH_SHORT).show()
            loadProfileIntoForm()
            setAccountMode(AccountMode.ACTIONS)
        }
    }

    private fun savePhoneInline() {
        val host = activity as? MainActivity ?: return
        val session = host.sessionStoreRef()
        val token = session.authToken()
        if (token.isBlank()) return

        val newPhone = binding.etChangePhone.text.toString().trim()
        binding.tvChangePhoneError.visibility = View.GONE

        scope.launch {
            val result = host.backendApiRef().updateProfile(
                token = token,
                email = session.email(),
                phone = newPhone,
                oldPassword = "",
                password = "",
                password2 = "",
            )
            if (!result.error.isNullOrBlank()) {
                binding.tvChangePhoneError.text = result.error
                binding.tvChangePhoneError.visibility = View.VISIBLE
                return@launch
            }
            val updated = result.data ?: return@launch
            val address = session.address()
            session.save(AuthSession(updated.token, updated.userId, updated.username, address))
            session.saveProfile(session.firstName(), session.lastName(), session.email(), newPhone)
            Toast.makeText(requireContext(), getString(R.string.settings_phone_updated), Toast.LENGTH_SHORT).show()
            loadProfileIntoForm()
            setAccountMode(AccountMode.ACTIONS)
        }
    }

    private fun savePasswordInline() {
        val host = activity as? MainActivity ?: return
        val session = host.sessionStoreRef()
        val token = session.authToken()
        if (token.isBlank()) return

        val oldPwd = binding.etChangePasswordOld.text.toString()
        val pwd1 = binding.etChangePasswordNew1.text.toString()
        val pwd2 = binding.etChangePasswordNew2.text.toString()

        binding.tvChangePasswordError.visibility = View.GONE
        when {
            oldPwd.isBlank() -> {
                binding.tvChangePasswordError.text = getString(R.string.settings_password_current_required)
                binding.tvChangePasswordError.visibility = View.VISIBLE
                return
            }
            pwd1.isBlank() || pwd2.isBlank() -> {
                binding.tvChangePasswordError.text = getString(R.string.settings_password_new_required)
                binding.tvChangePasswordError.visibility = View.VISIBLE
                return
            }
            pwd1 != pwd2 -> {
                binding.tvChangePasswordError.text = getString(R.string.settings_password_mismatch)
                binding.tvChangePasswordError.visibility = View.VISIBLE
                return
            }
            pwd1.length < 6 -> {
                binding.tvChangePasswordError.text = getString(R.string.settings_password_too_short)
                binding.tvChangePasswordError.visibility = View.VISIBLE
                return
            }
        }

        scope.launch {
            val result = host.backendApiRef().updateProfile(
                token = token,
                email = session.email(),
                phone = session.phone(),
                oldPassword = oldPwd,
                password = pwd1,
                password2 = pwd2,
            )
            if (!result.error.isNullOrBlank()) {
                binding.tvChangePasswordError.text = result.error
                binding.tvChangePasswordError.visibility = View.VISIBLE
                return@launch
            }
            val updated = result.data ?: return@launch
            val address = session.address()
            session.save(AuthSession(updated.token, updated.userId, updated.username, address))
            Toast.makeText(requireContext(), getString(R.string.settings_password_updated), Toast.LENGTH_SHORT).show()
            loadProfileIntoForm()
            setAccountMode(AccountMode.ACTIONS)
        }
    }

    private fun deleteAccountInline() {
        val host = activity as? MainActivity ?: return
        val session = host.sessionStoreRef()
        val token = session.authToken()
        if (token.isBlank()) return

        val sessionEmail = session.email().trim().lowercase(Locale.ROOT)
        val typedEmail = binding.etDeleteAccountEmailInline.text.toString().trim().lowercase(Locale.ROOT)
        val password = binding.etDeleteAccountPasswordInline.text.toString()

        binding.tvDeleteAccountError.visibility = View.GONE
        when {
            sessionEmail.isBlank() -> {
                binding.tvDeleteAccountError.text = getString(R.string.settings_delete_account_email_missing)
                binding.tvDeleteAccountError.visibility = View.VISIBLE
                return
            }
            typedEmail != sessionEmail -> {
                binding.tvDeleteAccountError.text = getString(R.string.settings_delete_account_email_mismatch)
                binding.tvDeleteAccountError.visibility = View.VISIBLE
                return
            }
            password.isBlank() -> {
                binding.tvDeleteAccountError.text = getString(R.string.settings_delete_account_password_required)
                binding.tvDeleteAccountError.visibility = View.VISIBLE
                return
            }
        }

        setDeleteButtonBusy(true)
        scope.launch {
            val result = host.backendApiRef().deleteAccount(token, typedEmail, password)
            setDeleteButtonBusy(false)
            if (!result.error.isNullOrBlank()) {
                binding.tvDeleteAccountError.text = result.error
                binding.tvDeleteAccountError.visibility = View.VISIBLE
                return@launch
            }
            Toast.makeText(requireContext(), getString(R.string.settings_delete_account_success), Toast.LENGTH_LONG).show()
            host.logout()
        }
    }

    private fun setDeleteButtonBusy(busy: Boolean) {
        binding.btnDeleteAccountConfirmInline.isEnabled = !busy
        binding.btnDeleteAccountConfirmInline.alpha = if (busy) 0.65f else 1f
    }

    private fun confirmClearConnections() {
        val host = activity as? MainActivity ?: return
        val count = host.currentPairings().count { it.paired && it.deviceId.isNotBlank() }
        if (count == 0) {
            Toast.makeText(requireContext(), getString(R.string.settings_clear_connections_empty), Toast.LENGTH_SHORT).show()
            return
        }
        ThemedDialogs.showConfirmation(
            context = requireContext(),
            title = getString(R.string.settings_clear_connections_confirm_title),
            message = getString(R.string.settings_clear_connections_confirm_message, count),
            positiveText = getString(R.string.settings_clear_connections_confirm_action),
            negativeText = getString(R.string.dialog_cancel),
            iconRes = R.drawable.ic_delete,
            destructive = true,
            onPositive = {
                clearAllConnections()
            },
        )
    }

    private fun clearAllConnections() {
        val host = activity as? MainActivity ?: return
        setClearButtonBusy(true)
        scope.launch {
            val result = host.clearAllPairingsFromUi()
            setClearButtonBusy(false)
            when {
                result.total == 0 -> {
                    Toast.makeText(requireContext(), getString(R.string.settings_clear_connections_empty), Toast.LENGTH_SHORT).show()
                }
                result.failed == 0 -> {
                    Toast.makeText(requireContext(), getString(R.string.settings_clear_connections_success, result.cleared), Toast.LENGTH_SHORT).show()
                }
                result.cleared == 0 -> {
                    Toast.makeText(requireContext(), getString(R.string.settings_clear_connections_failed), Toast.LENGTH_SHORT).show()
                }
                else -> {
                    Toast.makeText(requireContext(), getString(R.string.settings_clear_connections_partial, result.cleared, result.failed), Toast.LENGTH_SHORT).show()
                }
            }
            refreshContent()
        }
    }

    private fun setClearButtonBusy(busy: Boolean) {
        binding.btnProfileClearConnections.isEnabled = !busy
        binding.btnProfileClearConnections.alpha = if (busy) 0.65f else 1f
    }

    private fun loadNotificationSettings() {
        val host = activity as? MainActivity ?: return
        val settings = host.appSettingsStoreRef()
        binding.switchNotifyConnect.isChecked = settings.notifyOnConnect()
        binding.switchNotifyDisconnect.isChecked = settings.notifyOnDisconnect()
    }

    private fun bindAppInfo() {
        val context = context ?: return
        val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
        val versionName = packageInfo.versionName.orEmpty().ifBlank { "-" }
        val versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            packageInfo.longVersionCode
        } else {
            @Suppress("DEPRECATION")
            packageInfo.versionCode.toLong()
        }
        binding.tvAppVersion.text = getString(R.string.settings_app_version_value, versionName, versionCode.toString())
    }

    override fun onDestroyView() {
        scope.cancel()
        _binding = null
        super.onDestroyView()
    }
}
