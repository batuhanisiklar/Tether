package com.remotecontrol

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import com.remotecontrol.databinding.FragmentSettingsBinding

class SettingsFragment : Fragment(), DashboardFragment {
    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!

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
        binding.btnAccessibility.setOnClickListener {
            (activity as? MainActivity)?.openAccessibilitySettingsScreen()
        }
        binding.btnLogout.setOnClickListener {
            (activity as? MainActivity)?.logout()
        }
        refreshContent()
    }

    override fun onResume() {
        super.onResume()
        refreshContent()
    }

    override fun refreshContent() {
        val host = activity as? MainActivity ?: return
        binding.tvUsername.text = host.usernameText()
        binding.tvDeviceId.text = host.deviceSummaryText()
        binding.tvPairedPc.text = host.preferredPcText()
        binding.tvAccessibility.text = host.accessibilitySummaryText()
    }

    override fun onDestroyView() {
        _binding = null
        super.onDestroyView()
    }
}
