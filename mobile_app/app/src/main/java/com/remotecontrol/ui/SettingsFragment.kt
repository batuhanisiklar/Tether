package com.remotecontrol.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
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

class SettingsFragment : Fragment(), DashboardFragment {
    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

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
        binding.btnLogout.setOnClickListener {
            (activity as? MainActivity)?.logout()
        }
        binding.btnProfileEdit.setOnClickListener {
            openEditPanel()
        }
        binding.btnProfileChangePassword.setOnClickListener {
            openPasswordPanel()
        }
        binding.btnProfileCancel.setOnClickListener {
            cancelEdit()
        }
        binding.btnProfileSave.setOnClickListener {
            saveProfile()
        }
        binding.btnProfilePasswordCancel.setOnClickListener {
            cancelPassword()
        }
        binding.btnProfilePasswordSave.setOnClickListener {
            savePassword()
        }
        refreshContent()
        loadProfileIntoForm()
        setEditPanelOpen(false)
        setPasswordPanelOpen(false)
    }

    override fun onResume() {
        super.onResume()
        refreshContent()
    }

    override fun refreshContent() {
        val host = activity as? MainActivity ?: return
        binding.tvUsername.text = host.fullNameText()
        binding.tvDeviceId.text = host.deviceSummaryText()
        binding.tvProfileEmail.text = host.sessionStoreRef().email().ifBlank { "—" }
        binding.tvProfilePhone.text = formatPhoneLine(host.sessionStoreRef().phone())
        updateAvatarFromSession(host)
    }

    private fun formatPhoneLine(raw: String): String {
        val p = raw.trim()
        return if (p.isBlank()) "—" else p
    }

    private fun updateAvatarFromSession(host: MainActivity) {
        val fn = host.sessionStoreRef().firstName().trim()
        val ln = host.sessionStoreRef().lastName().trim()
        val email = host.sessionStoreRef().email().trim()
        binding.tvProfileAvatar.text = avatarLetters(fn, ln, email)
    }

    private fun avatarLetters(first: String, last: String, email: String): String {
        val a = first.firstOrNull()?.uppercaseChar()
        val b = last.firstOrNull()?.uppercaseChar()
        return when {
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
            binding.tvReadonlyFullName.text = listOf(p.firstName, p.lastName)
                .map { it.trim() }
                .filter { it.isNotBlank() }
                .joinToString(" ")
                .ifBlank { "—" }
            binding.etProfileEmail.setText(p.email)
            binding.etProfilePhone.setText(p.phone)
            refreshContent()
        }
    }

    private suspend fun fetchProfileWithRetry(
        host: MainActivity,
        token: String,
        deviceId: String,
    ): ApiResult<UserProfile> {
        var last: ApiResult<UserProfile> = ApiResult(error = "Kullanici bilgisi alinamadi.")
        repeat(3) { attempt ->
            val result = host.backendApiRef().getProfile(token, deviceId)
            if (result.data != null) return result
            last = result
            if (attempt < 2) delay(400L * (attempt + 1))
        }
        return last
    }

    private fun openEditPanel() {
        val host = activity as? MainActivity ?: return
        binding.etProfileEmail.setText(host.sessionStoreRef().email())
        binding.etProfilePhone.setText(host.sessionStoreRef().phone())
        binding.tvProfileError.visibility = View.GONE
        setPasswordPanelOpen(false)
        setEditPanelOpen(true)
    }

    private fun cancelEdit() {
        val host = activity as? MainActivity ?: return
        binding.etProfileEmail.setText(host.sessionStoreRef().email())
        binding.etProfilePhone.setText(host.sessionStoreRef().phone())
        binding.tvProfileError.visibility = View.GONE
        setEditPanelOpen(false)
    }

    private fun setEditPanelOpen(open: Boolean) {
        binding.layoutProfileEditPanel.visibility = if (open) View.VISIBLE else View.GONE
        binding.btnProfileEdit.visibility = if (open) View.GONE else View.VISIBLE
        binding.btnProfileChangePassword.visibility = if (open) View.GONE else View.VISIBLE
    }

    private fun setPasswordPanelOpen(open: Boolean) {
        binding.layoutProfilePasswordPanel.visibility = if (open) View.VISIBLE else View.GONE
        binding.btnProfileEdit.visibility = if (open) View.GONE else View.VISIBLE
        binding.btnProfileChangePassword.visibility = if (open) View.GONE else View.VISIBLE
    }

    private fun saveProfile() {
        val host = activity as? MainActivity ?: return
        val token = host.sessionStoreRef().authToken()
        if (token.isBlank()) return

        val email = binding.etProfileEmail.text.toString().trim()
        val phone = binding.etProfilePhone.text.toString().trim()

        binding.tvProfileError.visibility = View.GONE
        scope.launch {
            if (email.isBlank() || !email.contains("@")) {
                binding.tvProfileError.text = "Gecerli bir e-posta girin."
                binding.tvProfileError.visibility = View.VISIBLE
                return@launch
            }

            val result = host.backendApiRef().updateProfile(
                token = token,
                email = email,
                phone = phone,
                oldPassword = "",
                password = "",
                password2 = "",
            )
            if (!result.error.isNullOrBlank()) {
                binding.tvProfileError.text = result.error
                binding.tvProfileError.visibility = View.VISIBLE
                return@launch
            }
            val updated = result.data ?: return@launch
            val address = host.sessionStoreRef().address()
            host.sessionStoreRef().save(
                AuthSession(
                    token = updated.token,
                    userId = updated.userId,
                    username = updated.username,
                    address = address,
                )
            )
            host.sessionStoreRef().saveProfile(
                firstName = host.sessionStoreRef().firstName(),
                lastName = host.sessionStoreRef().lastName(),
                email = email,
                phone = phone,
            )
            Toast.makeText(requireContext(), "Profil guncellendi.", Toast.LENGTH_SHORT).show()
            setEditPanelOpen(false)
            loadProfileIntoForm()
        }
    }

    private fun openPasswordPanel() {
        binding.etProfileOldPassword.text?.clear()
        binding.etProfileNewPassword.text?.clear()
        binding.etProfileNewPassword2.text?.clear()
        binding.tvProfilePasswordError.visibility = View.GONE
        setEditPanelOpen(false)
        setPasswordPanelOpen(true)
    }

    private fun cancelPassword() {
        binding.etProfileOldPassword.text?.clear()
        binding.etProfileNewPassword.text?.clear()
        binding.etProfileNewPassword2.text?.clear()
        binding.tvProfilePasswordError.visibility = View.GONE
        setPasswordPanelOpen(false)
    }

    private fun savePassword() {
        val host = activity as? MainActivity ?: return
        val token = host.sessionStoreRef().authToken()
        if (token.isBlank()) return

        val email = host.sessionStoreRef().email().ifBlank { binding.etProfileEmail.text?.toString().orEmpty() }.trim()
        val phone = host.sessionStoreRef().phone().ifBlank { binding.etProfilePhone.text?.toString().orEmpty() }.trim()
        val oldPwd = binding.etProfileOldPassword.text.toString()
        val pwd1 = binding.etProfileNewPassword.text.toString()
        val pwd2 = binding.etProfileNewPassword2.text.toString()

        binding.tvProfilePasswordError.visibility = View.GONE
        scope.launch {
            if (oldPwd.isBlank()) {
                binding.tvProfilePasswordError.text = "Mevcut sifre gerekli."
                binding.tvProfilePasswordError.visibility = View.VISIBLE
                return@launch
            }
            if (pwd1.isBlank() || pwd2.isBlank()) {
                binding.tvProfilePasswordError.text = "Yeni sifre iki kere girilmelidir."
                binding.tvProfilePasswordError.visibility = View.VISIBLE
                return@launch
            }
            if (pwd1 != pwd2) {
                binding.tvProfilePasswordError.text = "Yeni sifreler eslesmiyor."
                binding.tvProfilePasswordError.visibility = View.VISIBLE
                return@launch
            }
            if (pwd1.length < 6) {
                binding.tvProfilePasswordError.text = "Sifre en az 6 karakter olmali."
                binding.tvProfilePasswordError.visibility = View.VISIBLE
                return@launch
            }
            val result = host.backendApiRef().updateProfile(
                token = token,
                email = email,
                phone = phone,
                oldPassword = oldPwd,
                password = pwd1,
                password2 = pwd2,
            )
            if (!result.error.isNullOrBlank()) {
                binding.tvProfilePasswordError.text = result.error
                binding.tvProfilePasswordError.visibility = View.VISIBLE
                return@launch
            }
            val updated = result.data ?: return@launch
            val address = host.sessionStoreRef().address()
            host.sessionStoreRef().save(AuthSession(updated.token, updated.userId, updated.username, address))
            Toast.makeText(requireContext(), "Sifre guncellendi.", Toast.LENGTH_SHORT).show()
            cancelPassword()
        }
    }

    override fun onDestroyView() {
        scope.cancel()
        _binding = null
        super.onDestroyView()
    }
}
