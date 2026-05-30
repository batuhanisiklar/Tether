package com.remotecontrol.ui

import android.graphics.Typeface
import android.os.Bundle
import android.util.TypedValue
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.remotecontrol.R
import com.remotecontrol.data.DeviceSummary
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
            .filter { it.deviceType == "pc" && it.paired }
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
            background = ContextCompat.getDrawable(
                requireContext(),
                if (device.online) R.drawable.device_card_online_bg else R.drawable.device_card_bg,
            )
            setPadding(dp(16), dp(16), dp(16), dp(16))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply {
                bottomMargin = dp(12)
            }
        }

        val headerRow = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
        }

        val deviceIcon = androidx.appcompat.widget.AppCompatImageView(requireContext()).apply {
            setImageResource(R.drawable.ic_devices)
            setColorFilter(ContextCompat.getColor(requireContext(), R.color.primary))
            contentDescription = getString(R.string.nav_devices)
            background = ContextCompat.getDrawable(requireContext(), R.drawable.card_soft_bg)
            setPadding(dp(8), dp(8), dp(8), dp(8))
            layoutParams = LinearLayout.LayoutParams(dp(36), dp(36)).apply {
                rightMargin = dp(10)
            }
        }
        headerRow.addView(deviceIcon)

        val title = TextView(requireContext()).apply {
            text = device.username?.takeIf { it.isNotBlank() } ?: host.usernameText()
            setTextColor(ContextCompat.getColor(requireContext(), R.color.text_primary))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            setTypeface(typeface, Typeface.BOLD)
        }
        headerRow.addView(title)

        val statusLabel = TextView(requireContext()).apply {
            text = if (device.online) getString(R.string.device_status_online) else getString(R.string.device_status_offline)
            setTextColor(
                ContextCompat.getColor(
                    requireContext(),
                    if (device.online) R.color.success else R.color.danger,
                ),
            )
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            setPadding(dp(10), dp(4), dp(10), dp(4))
            background = ContextCompat.getDrawable(
                requireContext(),
                if (device.online) R.drawable.device_status_chip_online else R.drawable.device_status_chip_offline,
            )
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { leftMargin = dp(8) }
        }
        headerRow.addView(statusLabel)

        val spacer = View(requireContext()).apply {
            layoutParams = LinearLayout.LayoutParams(0, 0, 1f)
        }
        headerRow.addView(spacer)

        val deleteButton = androidx.appcompat.widget.AppCompatImageButton(requireContext()).apply {
            setImageResource(R.drawable.ic_delete)
            setColorFilter(ContextCompat.getColor(requireContext(), R.color.text_primary))
            contentDescription = getString(R.string.remove_device)
            background = ContextCompat.getDrawable(requireContext(), R.drawable.card_soft_bg)
            setPadding(dp(8), dp(8), dp(8), dp(8))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            )
            setOnClickListener {
                ThemedDialogs.showConfirmation(
                    context = requireContext(),
                    title = getString(R.string.remove_device),
                    message = getString(R.string.forget_pairing_confirm),
                    positiveText = getString(R.string.forget_device),
                    negativeText = getString(R.string.dialog_cancel),
                    iconRes = R.drawable.ic_delete,
                    destructive = true,
                    onPositive = {
                        host.forgetPairingFromUi(device.deviceId, device.address)
                    },
                )
            }
        }
        headerRow.addView(deleteButton)

        row.addView(headerRow)

        val detailsBox = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            background = ContextCompat.getDrawable(requireContext(), R.drawable.guide_question_bg)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(10) }
        }

        val deviceNameLine = TextView(requireContext()).apply {
            text = getString(
                R.string.devices_item_device_name,
                device.deviceName?.takeIf { it.isNotBlank() } ?: getString(R.string.devices_item_unknown),
            )
            setTextColor(ContextCompat.getColor(requireContext(), R.color.text_secondary))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        }
        detailsBox.addView(deviceNameLine)

        val deviceNoLine = TextView(requireContext()).apply {
            text = getString(R.string.devices_item_device_number, formatDeviceNumber(device))
            setTextColor(ContextCompat.getColor(requireContext(), R.color.text_tertiary))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            setPadding(0, dp(4), 0, 0)
        }
        detailsBox.addView(deviceNoLine)
        row.addView(detailsBox)

        return row
    }

    private fun formatDeviceNumber(device: DeviceSummary): String {
        val digits = device.address
            ?.takeIf { it.isNotBlank() }
            ?.filter { it.isDigit() }
            ?.take(12)
            .orEmpty()
        if (digits.isNotBlank()) return digits.chunked(4).joinToString("-")
        return device.deviceId.takeLast(12).ifBlank { getString(R.string.devices_item_unknown) }
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

