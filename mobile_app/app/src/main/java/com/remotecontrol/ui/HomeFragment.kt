package com.remotecontrol.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.remotecontrol.R
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
        binding.btnHomeCopyCode.setOnClickListener {
            val host = activity as? MainActivity ?: return@setOnClickListener
            val raw = host.sessionStoreRef().address().filter(Char::isDigit).take(12)
            if (raw.isBlank()) return@setOnClickListener
            val clipboard = requireContext().getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
            clipboard.setPrimaryClip(android.content.ClipData.newPlainText("address", raw))
            android.widget.Toast.makeText(requireContext(), getString(R.string.copied), android.widget.Toast.LENGTH_SHORT).show()
        }
        binding.btnHomeShareCode.setOnClickListener {
            val host = activity as? MainActivity ?: return@setOnClickListener
            val raw = host.sessionStoreRef().address().filter(Char::isDigit).take(12)
            if (raw.isBlank()) return@setOnClickListener
            val formatted = raw.chunked(4).joinToString("-")
            val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(android.content.Intent.EXTRA_TEXT, formatted)
            }
            runCatching {
                startActivity(android.content.Intent.createChooser(intent, getString(R.string.share)))
            }.onFailure {
                val clipboard = requireContext().getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                clipboard.setPrimaryClip(android.content.ClipData.newPlainText("address", raw))
                android.widget.Toast.makeText(requireContext(), getString(R.string.copied), android.widget.Toast.LENGTH_SHORT).show()
            }
        }
        refreshContent()
    }

    override fun onResume() {
        super.onResume()
        refreshContent()
    }

    override fun refreshContent() {
        val host = activity as? MainActivity ?: return
        binding.tvUser.text = host.homeUserDisplayText()
        binding.tvCode.text = host.currentCodeText()
        binding.tvHomeAccessibility.text = host.accessibilitySummaryText()
        val a11yOn = host.isAccessibilityServiceEnabledForUi()
        val events = host.recentEventLines(limit = 5)
        val eventViews = listOf(
            binding.tvHomeEvent1,
            binding.tvHomeEvent2,
            binding.tvHomeEvent3,
            binding.tvHomeEvent4,
            binding.tvHomeEvent5,
        )
        eventViews.forEachIndexed { index, textView ->
            val line = events.getOrNull(index)
            if (line == null) {
                textView.text = getString(R.string.home_recent_events_empty)
                textView.visibility = if (index == 0) View.VISIBLE else View.GONE
            } else {
                textView.text = line
                textView.visibility = View.VISIBLE
            }
        }
        val ctx = requireContext()
        binding.layoutHomeAccessibilityCard.setBackgroundResource(
            if (a11yOn) R.drawable.home_accessibility_success_bg else R.drawable.card_warning_bg,
        )
        binding.tvHomeAccessibility.setTextColor(
            ContextCompat.getColor(ctx, if (a11yOn) R.color.success else R.color.warning),
        )
        if (a11yOn) {
            binding.tvHomeAccessibilityStepsTitle.text = getString(R.string.home_accessibility_steps_title_enabled)
            binding.tvHomeAccessibilityStep1.text = getString(R.string.home_accessibility_enabled_step_1)
            binding.tvHomeAccessibilityStep2.text = getString(R.string.home_accessibility_enabled_step_2)
            binding.tvHomeAccessibilityStep3.text = getString(R.string.home_accessibility_enabled_step_3)
        } else {
            binding.tvHomeAccessibilityStepsTitle.text = getString(R.string.home_accessibility_steps_title)
            binding.tvHomeAccessibilityStep1.text = getString(R.string.home_accessibility_step_1)
            binding.tvHomeAccessibilityStep2.text = getString(R.string.home_accessibility_step_2)
            binding.tvHomeAccessibilityStep3.text = getString(R.string.home_accessibility_step_3)
        }
        binding.layoutHomeAccessibilitySteps.visibility = View.VISIBLE
        binding.btnHomeAccessibility.visibility = if (a11yOn) View.GONE else View.VISIBLE
    }

    override fun onDestroyView() {
        _binding = null
        super.onDestroyView()
    }
}
