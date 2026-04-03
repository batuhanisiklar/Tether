package com.remotecontrol

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
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
        binding.btnConnect.setOnClickListener {
            (activity as? MainActivity)?.reconnect()
        }
        binding.btnStartStream.setOnClickListener {
            (activity as? MainActivity)?.startScreenShareFromUser()
        }
        binding.btnStopStream.setOnClickListener {
            (activity as? MainActivity)?.stopStreamsFromUi()
        }
        refreshContent()
    }

    override fun onResume() {
        super.onResume()
        refreshContent()
    }

    override fun refreshContent() {
        val host = activity as? MainActivity ?: return
        binding.tvUser.text = host.usernameText()
        binding.tvCode.text = host.currentCodeText()
        binding.tvStatus.text = host.statusText()
        binding.tvStatusDetail.text = host.statusDetailText()
        binding.btnConnect.isEnabled = host.canReconnect()
        val showStart = host.canStartScreenShare()
        binding.btnStartStream.visibility = if (showStart) View.VISIBLE else View.GONE
        binding.btnStartStream.isEnabled = showStart
        binding.btnStopStream.isEnabled = host.canStopStream()
    }

    override fun onDestroyView() {
        _binding = null
        super.onDestroyView()
    }
}
