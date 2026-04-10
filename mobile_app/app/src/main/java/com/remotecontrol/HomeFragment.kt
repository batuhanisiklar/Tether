package com.remotecontrol

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.remotecontrol.databinding.FragmentHomeBinding

class HomeFragment : Fragment(), DashboardFragment {
    private var _binding: FragmentHomeBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentHomeBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        binding.btnHomeAccessibility.setOnClickListener {
            (activity as? MainActivity)?.openAccessibilitySettingsScreen()
        }
        refreshContent()
    }

    override fun onResume() {
        super.onResume()
        refreshContent()
    }

    override fun refreshContent() {
        val host = activity as? MainActivity ?: return
        binding.tvUser.text = host.fullNameText()
        binding.tvCode.text = host.currentCodeText()
        binding.tvHomeAccessibility.text = host.accessibilitySummaryText()
        val a11yOn = host.isAccessibilityServiceEnabledForUi()
        val ctx = requireContext()
        binding.layoutHomeAccessibilityCard.setBackgroundResource(
            if (a11yOn) R.drawable.home_accessibility_success_bg else R.drawable.card_warning_bg,
        )
        binding.tvHomeAccessibility.setTextColor(
            ContextCompat.getColor(ctx, if (a11yOn) R.color.success else R.color.warning),
        )
        binding.btnHomeAccessibility.visibility = if (a11yOn) View.GONE else View.VISIBLE
    }

    override fun onDestroyView() {
        _binding = null
        super.onDestroyView()
    }
}
