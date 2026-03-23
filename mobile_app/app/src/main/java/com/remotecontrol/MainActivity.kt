package com.remotecontrol

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.text.format.Formatter
import android.util.Log
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.remotecontrol.databinding.ActivityMainBinding
import kotlinx.coroutines.*

/**
 * Ana Aktivite
 * ============
 * - Kalıcı device_id ile sunucuya bağlanır (device_hello)
 * - PC daha önce eşleşmişse auto_paired tetiklenir — kod gerekmez
 * - İlk eşleşme: 6 haneli kod PC'den girilir
 * - Eşleşme sonrası pair_confirm sunucuya gönderilir ve SharedPreferences'e kaydedilir
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "MainActivity"
        const val SIGNALING_URL = "wss://connect-your-phone.onrender.com"

        private val IS_EMULATOR = (android.os.Build.FINGERPRINT.startsWith("generic")
                || android.os.Build.FINGERPRINT.startsWith("unknown")
                || android.os.Build.MODEL.contains("Emulator")
                || android.os.Build.MODEL.contains("Android SDK built for x86")
                || android.os.Build.MANUFACTURER.contains("Genymotion")
                || android.os.Build.BRAND.startsWith("generic"))
    }

    // UI
    private lateinit var binding: ActivityMainBinding
    private lateinit var sessionStore: SessionStore
    private lateinit var deviceIdentityStore: DeviceIdentityStore
    private lateinit var backendApi: BackendApi

    // Network
    private var signalingClient: SignalingClient? = null
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    // Cihaz kimliği
    private lateinit var deviceId: String
    private var pairedPcId: String? = null

    private val mediaProjectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            startScreenStream(result.resultCode, result.data!!)
        } else {
            updateStatus("⚠ Ekran kaydı izni reddedildi")
        }
    }

    // Kamera izni
    private val cameraPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            startCameraStream(useFront = false)
        } else {
            updateStatus("⚠ Kamera izni reddedildi")
        }
    }

    // Bildirim izni (Android 13+)
    private val notifPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* İzin verilmese de devam et */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        sessionStore = SessionStore(this)
        deviceIdentityStore = DeviceIdentityStore(this)
        backendApi = BackendApi(SIGNALING_URL)

        if (!sessionStore.isLoggedIn()) {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        deviceId = deviceIdentityStore.deviceId()
        pairedPcId = deviceIdentityStore.pairedPcId()
        Log.i(TAG, "Device ID: $deviceId, pairedPcId: $pairedPcId")

        initViews()
        requestNotificationPermission()
        checkAccessibilityService()
        scope.launch {
            syncDeviceState()
            refreshPairings()
        }
        autoConnect()
    }

    private fun initViews() {
        binding.btnConnect.setOnClickListener { autoConnect() }
        binding.btnStopStream.setOnClickListener { stopAllStreams() }
        binding.btnLogout.setOnClickListener { logout() }
        binding.tvAccessibility.setOnClickListener {
            startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        binding.btnStopStream.isEnabled = false
        binding.tvUser.text = sessionStore.username().ifBlank { "Kullanici" }

        if (pairedPcId != null) {
            val shortId = pairedPcId!!.takeLast(8)
            binding.tvIpPort.text = "Kayıtlı PC: ...$shortId"
        }
    }

    private fun autoConnect() {
        updateStatus("🔄 Signaling sunucusuna bağlanıyor...")
        binding.btnConnect.isEnabled = false

        signalingClient?.disconnect()
        signalingClient = SignalingClient(
            serverUrl  = SIGNALING_URL,
            deviceId   = deviceId,
            onPaired   = { _, partnerDeviceId ->
                runOnUiThread {
                    if (!partnerDeviceId.isNullOrBlank()) {
                        onFirstPairComplete(partnerDeviceId)
                    }
                    updateStatus("✅ PC bağlandı!")
                    binding.btnStopStream.isEnabled = true
                    scope.launch { refreshPairings() }
                    if (IS_EMULATOR) {
                        updateStatus("✅ PC bağlandı! Kamera yayını başlıyor (emülatör)...")
                        requestCameraAccess(useFront = false)
                    } else {
                        updateStatus("✅ PC bağlandı! Ekran yayını başlıyor...")
                        requestScreenCapture()
                    }
                }
            },
            onCommand  = { action, params -> handleCommand(action, params) },
            onDisconnected = {
                runOnUiThread {
                    updateStatus("🔴 Bağlantı kesildi — Yeniden bağlanmak için butona basın")
                    binding.btnConnect.isEnabled = true
                    binding.btnStopStream.isEnabled = false
                    stopAllStreams()
                }
            }
        )
        signalingClient?.connect()

        // 6-haneli kodu göster (ilk eşleşme için)
        val code = signalingClient!!.sessionCode
        binding.tvCode.text = code

        val statusMsg = if (pairedPcId != null)
            "⏳ Kayıtlı PC bekleniyor... (Kod: $code)"
        else
            "⏳ PC bağlantısı bekleniyor... (Kod: $code)"
        updateStatus(statusMsg)
        Log.i(TAG, "Session code: $code")
    }

    /**
     * İlk eşleşme tamamlandığında çağrılır.
     * PC'nin device_id'si bilinmiyorsa bu metod pas geçilir;
     * sunucu pair_confirm'i iki taraftan birinin gönderimi yeterlidir.
     */
    fun onFirstPairComplete(pcDeviceId: String) {
        if (pcDeviceId.isBlank()) return
        deviceIdentityStore.savePairedPcId(pcDeviceId)
        pairedPcId = pcDeviceId
        signalingClient?.sendPairConfirm(pcDeviceId)
        Log.i(TAG, "Pair confirmed with PC: $pcDeviceId")
    }

    private fun handleCommand(action: String, params: Map<String, Any>) {
        Log.d(TAG, "Command: $action $params")
        when (action) {
            "touch" -> {
                val x = (params["x"] as? Double)?.toFloat() ?: return
                val y = (params["y"] as? Double)?.toFloat() ?: return
                ControlReceiver.instance?.performTouch(x, y)
            }
            "swipe" -> {
                val x1 = (params["x1"] as? Double)?.toFloat() ?: return
                val y1 = (params["y1"] as? Double)?.toFloat() ?: return
                val x2 = (params["x2"] as? Double)?.toFloat() ?: return
                val y2 = (params["y2"] as? Double)?.toFloat() ?: return
                ControlReceiver.instance?.performSwipe(x1, y1, x2, y2)
            }
            "key_event" -> {
                val keyCode = (params["key_code"] as? Number)?.toInt() ?: return
                ControlReceiver.instance?.performKeyEvent(keyCode)
            }
            "rotate_screen" -> {
                val landscape = params["landscape"] as? Boolean ?: false
                runOnUiThread {
                    requestedOrientation = if (landscape)
                        android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
                    else
                        android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                }
            }
            "camera_on"  -> { runOnUiThread { requestCameraAccess(useFront = false) } }
            "camera_off" -> { runOnUiThread { stopCameraStream() } }
            else -> Log.w(TAG, "Unknown command: $action")
        }
    }

    private fun requestScreenCapture() {
        val pm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjectionLauncher.launch(pm.createScreenCaptureIntent())
    }

    private fun startScreenStream(resultCode: Int, data: Intent) {
        val intent = Intent(this, ScreenStreamService::class.java).apply {
            putExtra(ScreenStreamService.EXTRA_RESULT_CODE, resultCode)
            putExtra(ScreenStreamService.EXTRA_RESULT_DATA, data)
        }
        startForegroundService(intent)

        val ip = getDeviceIp()
        if (ip != "0.0.0.0" && !ip.startsWith("10.0.2.")) {
            val streamUrl = "http://$ip:${ScreenStreamService.PORT}/stream"
            signalingClient?.notifyStreamReady(streamUrl)
            binding.tvIpPort.text = "Stream: $streamUrl"
        } else {
            signalingClient?.notifyStreamReady("")
            binding.tvIpPort.text = "Ekran WebSocket üzerinden gönderiliyor"
        }
        updateStatus("🟢 Ekran yayını aktif")
    }

    private fun requestCameraAccess(useFront: Boolean) {
        when {
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                    == PackageManager.PERMISSION_GRANTED -> startCameraStream(useFront)
            else -> cameraPermLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startCameraStream(useFront: Boolean) {
        val intent = Intent(this, CameraStreamService::class.java).apply {
            putExtra(CameraStreamService.EXTRA_USE_FRONT, useFront)
        }
        startForegroundService(intent)

        val ip = getDeviceIp()
        if (ip != "0.0.0.0" && !ip.startsWith("10.0.2.")) {
            val streamUrl = "http://$ip:${CameraStreamService.PORT}/stream"
            signalingClient?.notifyStreamReady(streamUrl)
            binding.tvIpPort.text = "Kamera: $streamUrl"
        } else {
            signalingClient?.notifyStreamReady("")
            binding.tvIpPort.text = "Kamera WebSocket üzerinden gönderiliyor"
        }
        updateStatus("📷 Kamera yayını aktif")
    }

    private fun stopCameraStream() {
        stopService(Intent(this, CameraStreamService::class.java))
        updateStatus("🟢 Ekran yayını aktif (kamera kapatıldı)")
    }

    private fun stopAllStreams() {
        stopService(Intent(this, ScreenStreamService::class.java))
        stopService(Intent(this, CameraStreamService::class.java))
        binding.btnStopStream.isEnabled = false
        binding.tvIpPort.text = ""
        updateStatus("⏹ Tüm yayınlar durduruldu")
    }

    private suspend fun syncDeviceState() {
        val token = sessionStore.authToken()
        if (token.isBlank()) return
        backendApi.upsertDevice(token, deviceId, "phone")
    }

    private suspend fun refreshPairings() {
        val token = sessionStore.authToken()
        if (token.isBlank()) return
        val result = backendApi.getPairings(token, deviceId)
        val pairings = result.data ?: emptyList()
        if (pairings.isEmpty()) {
            binding.tvPairedDevices.text = "Henüz eşleşmiş bilgisayar yok."
            return
        }

        val summary = buildString {
            pairings.forEach { device ->
                val shortId = device.deviceId.takeLast(8)
                val state = if (device.online) "cevrimici" else "offline"
                append("• ...")
                append(shortId)
                append("  ")
                append(state)
                if (!device.lastSeen.isNullOrBlank()) {
                    append("\n  Son gorulme: ")
                    append(device.lastSeen)
                }
                append("\n")
            }
        }.trim()
        binding.tvPairedDevices.text = summary
    }

    private fun logout() {
        stopAllStreams()
        signalingClient?.disconnect()
        sessionStore.clear()
        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }

    private fun checkAccessibilityService() {
        val isEnabled = isAccessibilityServiceEnabled()
        binding.tvAccessibility.text = if (isEnabled)
            "✅ Erişilebilirlik servisi aktif"
        else
            "⚠ Dokunma kontrolü için buraya tıklayın (Erişilebilirlik aktif et)"
    }

    private fun isAccessibilityServiceEnabled(): Boolean {
        val serviceName = "$packageName/${ControlReceiver::class.java.name}"
        val setting = android.provider.Settings.Secure.getString(
            contentResolver,
            android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false
        return setting.contains(serviceName)
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun getDeviceIp(): String {
        if (IS_EMULATOR) return "127.0.0.1"
        return try {
            val wm = applicationContext.getSystemService(WIFI_SERVICE) as android.net.wifi.WifiManager
            @Suppress("DEPRECATION")
            val wifiIp = Formatter.formatIpAddress(wm.connectionInfo.ipAddress)
            if (wifiIp != "0.0.0.0") {
                wifiIp
            } else {
                val interfaces = java.util.Collections.list(java.net.NetworkInterface.getNetworkInterfaces())
                for (intf in interfaces) {
                    val addrs = java.util.Collections.list(intf.inetAddresses)
                    for (addr in addrs) {
                        if (!addr.isLoopbackAddress && addr is java.net.Inet4Address) {
                            return addr.hostAddress ?: "0.0.0.0"
                        }
                    }
                }
                "0.0.0.0"
            }
        } catch (e: Exception) {
            "0.0.0.0"
        }
    }

    private fun updateStatus(msg: String) {
        Log.i(TAG, msg)
        if (binding.tvStatus.text.toString() != msg) {
            binding.tvStatus.text = msg
        }
    }

    override fun onResume() {
        super.onResume()
        if (sessionStore.isLoggedIn()) {
            scope.launch { refreshPairings() }
        }
    }

    override fun onDestroy() {
        scope.cancel()
        signalingClient?.disconnect()
        super.onDestroy()
    }
}
