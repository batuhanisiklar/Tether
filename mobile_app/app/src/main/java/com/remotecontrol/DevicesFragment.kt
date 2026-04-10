package com.remotecontrol

import android.graphics.Typeface
import android.os.Bundle
import android.util.TypedValue
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.view.ContextThemeWrapper
import androidx.appcompat.widget.AppCompatButton
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.remotecontrol.databinding.FragmentDevicesBinding

class DevicesFragment : Fragment(), DashboardFragment {
    private var _binding: FragmentDevicesBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentDevicesBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        refreshContent()
    }

    override fun onResume() {
        super.onResume()
        refreshContent()
    }

    override fun refreshContent() {
        val host = activity as? MainActivity ?: return
        val devices = host.currentPairings()
        binding.layoutDevices.removeAllViews()
        if (devices.isEmpty()) {
            binding.tvEmptyState.visibility = View.VISIBLE
            binding.layoutDevices.visibility = View.GONE
            return
        }
        binding.tvEmptyState.visibility = View.GONE
        binding.layoutDevices.visibility = View.VISIBLE
        devices.forEach { device ->
            binding.layoutDevices.addView(buildRow(device, host))
        }
    }

    private fun buildRow(device: DeviceSummary, host: MainActivity): View {
        val row = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            background = ContextCompat.getDrawable(requireContext(), R.drawable.card_bg)
            setPadding(dp(14), dp(14), dp(14), dp(14))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply {
                bottomMargin = dp(10)
            }
        }

        val headerRow = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
        }

        val statusDot = View(requireContext()).apply {
            val dotColor = if (device.online) R.color.success else R.color.danger
            setBackgroundColor(ContextCompat.getColor(requireContext(), dotColor))
            layoutParams = LinearLayout.LayoutParams(dp(8), dp(8))
        }
        headerRow.addView(statusDot)

        val title = TextView(requireContext()).apply {
            text = device.displayName()
            setTextColor(ContextCompat.getColor(requireContext(), R.color.text_primary))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setTypeface(typeface, Typeface.BOLD)
            setPadding(dp(10), 0, 0, 0)
        }
        headerRow.addView(title)

        val statusLabel = TextView(requireContext()).apply {
            text = if (device.online) "Cevrimici" else "Offline"
            setTextColor(ContextCompat.getColor(requireContext(),
                if (device.online) R.color.success else R.color.text_tertiary))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            setPadding(dp(8), 0, 0, 0)
        }
        headerRow.addView(statusLabel)
        row.addView(headerRow)

        val subtitle = TextView(requireContext()).apply {
            val addressPart = device.address
                ?.takeIf { it.isNotBlank() }
                ?.filter { it.isDigit() }
                ?.take(12)
                ?.chunked(4)
                ?.joinToString("-")
            val statusPart = if (device.online) "Aktif" else "Cevrimdisi"
            text = listOfNotNull(addressPart, statusPart).joinToString("  •  ")
            setTextColor(ContextCompat.getColor(requireContext(), R.color.text_tertiary))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            setPadding(dp(18), dp(4), 0, 0)
        }
        row.addView(subtitle)

        val actions = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply {
                topMargin = dp(10)
            }
        }

        val forgetButton = AppCompatButton(
            ContextThemeWrapper(requireContext(), R.style.WidgetRemoteControlSecondaryButton),
            null, 0,
        ).apply {
            text = getString(R.string.remove_device)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            )
            setOnClickListener {
                AlertDialog.Builder(requireContext())
                    .setMessage(getString(R.string.forget_pairing_confirm))
                    .setPositiveButton(R.string.forget_device) { _, _ ->
                        host.forgetPairingFromUi(device.deviceId, device.address)
                    }
                    .setNegativeButton(android.R.string.cancel, null)
                    .show()
            }
        }
        actions.addView(forgetButton)
        row.addView(actions)
        return row
    }

    private fun dp(value: Int): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP,
        value.toFloat(),
        resources.displayMetrics,
    ).toInt()

    override fun onDestroyView() {
        _binding = null
        super.onDestroyView()
    }
}
