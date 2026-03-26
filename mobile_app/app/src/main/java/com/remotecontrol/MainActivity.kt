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
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.remotecontrol.databinding.ActivityMainBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

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

        fun buildDeviceName(): String {
            val manufacturer = Build.MANUFACTURER.trim()
            val model = Build.MODEL.trim()
            if (model.isBlank()) return manufacturer.ifBlank { "Android cihaz" }
            return if (manufacturer.isBlank() || model.startsWith(manufacturer, ignoreCase = true)) {
                model
            } else {
                "$manufacturer $model"
            }
        }
    }

    private lateinit var binding: ActivityMainBinding
    private lateinit var sessionStore: SessionStore
    private lateinit var deviceIdentityStore: DeviceIdentityStore
    private lateinit var backendApi: BackendApi

    private var signalingClient: SignalingClient? = null
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private lateinit var deviceId: String
    private val deviceName: String by lazy { buildDeviceName() }
    private var pairedPcId: String? = null
    private var currentStatus = "Baslatiliyor..."
    private var currentStatusDetail = ""
    private var currentAddress = "------------"
    private var currentPairings: List<DeviceSummary> = emptyList()
    private var streamRunning = false
    private var accessibilityEnabled = false

    private val mediaProjectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            startScreenStream(result.resultCode, result.data!!)
        } else {
            updateStatus("Ekran kaydi izni reddedildi")
        }
    }

    private val cameraPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            startCameraStream(useFront = false)
        } else {
            updateStatus("Kamera izni reddedildi")
        }
    }

    private val notifPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

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
        accessibilityEnabled = isAccessibilityServiceEnabled()
        currentAddress = sessionStore.address().ifBlank { "------------" }

        setupNavigation(savedInstanceState == null)
        requestNotificationPermission()

        scope.launch {
            syncUserProfile()
            syncDeviceState()
            refreshPairings()
        }
        autoConnect(pairedPcId)
    }

    private fun setupNavigation(initialSelect: Boolean) {
        binding.bottomNavigation.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_home -> showFragment("home") { HomeFragment() }
                R.id.nav_devices -> showFragment("devices") { DevicesFragment() }
                else -> false
            }
        }
        if (initialSelect) {
            binding.bottomNavigation.selectedItemId = R.id.nav_home
        }
    }

    private fun showFragment(tag: String, create: () -> Fragment): Boolean {
        val fragment = supportFragmentManager.findFragmentByTag(tag) ?: create()
        supportFragmentManager.beginTransaction()
            .replace(binding.fragmentContainer.id, fragment, tag)
            .commit()
        return true
    }

    fun reconnect() {
        autoConnect(pairedPcId)
    }

    fun connectToPairedDevice(partnerDeviceId: String) {
        deviceIdentityStore.savePairedPcId(partnerDeviceId)
        pairedPcId = partnerDeviceId
        updateStatus("Secilen bilgisayara baglaniliyor")
        refreshFragments()
        autoConnect(partnerDeviceId)
    }

    fun stopStreamsFromUi() {
        stopAllStreams()
    }

    fun forgetPairingFromUi(partnerDeviceId: String) {
        scope.launch {
            val token = sessionStore.authToken()
            if (token.isBlank()) return@launch
            val result = backendApi.deletePairing(token, deviceId, partnerDeviceId)
            if (result.error.isNullOrBlank()) {
                if (pairedPcId == partnerDeviceId) {
                    deviceIdentityStore.clearPairedPcId()
                    pairedPcId = null
                }
                Toast.makeText(this@MainActivity, getString(R.string.forget_pairing_success), Toast.LENGTH_SHORT).show()
                refreshPairings()
            } else {
                Toast.makeText(this@MainActivity, result.error, Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun openAccessibilitySettingsScreen() {
        startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS))
    }

    fun logout() {
        stopAllStreams()
        signalingClient?.disconnect()
        sessionStore.clear()
        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }

    fun usernameText(): String = sessionStore.username().ifBlank { "Kullanici" }

    fun currentCodeText(): String = formatAddressForUi(currentAddress)

    fun statusText(): String = currentStatus

    fun statusDetailText(): String = currentStatusDetail

    fun currentPairings(): List<DeviceSummary> = currentPairings

    fun canReconnect(): Boolean = true

    fun canStopStream(): Boolean = streamRunning

    fun deviceSummaryText(): String = "Bu cihaz: $deviceName"

    fun preferredPcText(): String {
        val pairedId = pairedPcId ?: return "Tercihli bilgisayar yok"
        val pairedDevice = currentPairings.firstOrNull { it.deviceId == pairedId }
        val displayName = pairedDevice?.displayName() ?: "...${pairedId.takeLast(8)}"
        return "Tercihli bilgisayar: $displayName"
    }

    fun accessibilitySummaryText(): String = if (accessibilityEnabled) {
        "Erisilebilirlik servisi aktif"
    } else {
        "Dokunma kontrolu icin erisilebilirlik servisini acin"
    }

    private fun autoConnect(preferredPartnerId: String?) {
        currentStatus = "Signaling sunucusuna baglaniyor"
        currentStatusDetail = preferredPartnerId?.let { "Tercihli bilgisayar: ...${it.takeLast(8)}" }.orEmpty()
        refreshFragments()

        signalingClient?.disconnect()
        signalingClient = SignalingClient(
            serverUrl = SIGNALING_URL,
            deviceId = deviceId,
            preferredPartnerId = preferredPartnerId,
            onPaired = { _, partnerDeviceId ->
                runOnUiThread {
                    if (!partnerDeviceId.isNullOrBlank()) {
                        onFirstPairComplete(partnerDeviceId)
                    }
                    streamRunning = true
                    scope.launch { refreshPairings() }
                    if (IS_EMULATOR) {
                        updateStatus("Bilgisayar baglandi, kamera yayini baslatiliyor")
                        requestCameraAccess(useFront = false)
                    } else {
                        updateStatus("Bilgisayar baglandi, ekran yayini baslatiliyor")
                        requestScreenCapture()
                    }
                }
            },
            onCommand = { action, params -> handleCommand(action, params) },
            onDisconnected = {
                runOnUiThread {
                    streamRunning = false
                    stopAllStreams()
                    currentStatus = "Baglanti kesildi"
                    currentStatusDetail = "Yeniden baglanmak icin Anasayfa veya Cihazlar sekmesini kullanin."
                    refreshFragments()
                }
            },
        )
        signalingClient?.connect()
        currentStatus = if (preferredPartnerId != null) {
            "Kayitli bilgisayar bekleniyor"
        } else {
            "Bilgisayar baglantisi bekleniyor"
        }
        currentStatusDetail = "Adres: $currentAddress"
        refreshFragments()
        Log.i(TAG, "Account address: $currentAddress")
    }

    private fun onFirstPairComplete(pcDeviceId: String) {
        if (pcDeviceId.isBlank()) return
        deviceIdentityStore.savePairedPcId(pcDeviceId)
        pairedPcId = pcDeviceId
        signalingClient?.sendPairConfirm(pcDeviceId)
        refreshFragments()
        Log.i(TAG, "Pair confirmed with PC: $pcDeviceId")
    }

    private fun handleCommand(action: String, params: Map<String, Any>) {
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
                    requestedOrientation = if (landscape) {
                        android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
                    } else {
                        android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                    }
                }
            }
            "camera_on" -> runOnUiThread { requestCameraAccess(useFront = false) }
            "camera_off" -> runOnUiThread { stopCameraStream() }
            else -> Log.w(TAG, "Unknown command: $action")
        }
    }

    private fun requestScreenCapture() {
        val projectionManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjectionLauncher.launch(projectionManager.createScreenCaptureIntent())
    }

    private fun startScreenStream(resultCode: Int, data: Intent) {
        val intent = Intent(this, ScreenStreamService::class.java).apply {
            putExtra(ScreenStreamService.EXTRA_RESULT_CODE, resultCode)
            putExtra(ScreenStreamService.EXTRA_RESULT_DATA, data)
        }
        startForegroundService(intent)

        val ip = getDeviceIp()
        currentStatusDetail = if (ip != "0.0.0.0" && !ip.startsWith("10.0.2.")) {
            val streamUrl = "http://$ip:${ScreenStreamService.PORT}/stream"
            signalingClient?.notifyStreamReady(streamUrl)
            "Yayin: $streamUrl"
        } else {
            signalingClient?.notifyStreamReady("")
            "Ekran WebSocket uzerinden gonderiliyor"
        }
        streamRunning = true
        updateStatus("Ekran yayini aktif")
    }

    private fun requestCameraAccess(useFront: Boolean) {
        when {
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED -> {
                startCameraStream(useFront)
            }
            else -> cameraPermLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startCameraStream(useFront: Boolean) {
        val intent = Intent(this, CameraStreamService::class.java).apply {
            putExtra(CameraStreamService.EXTRA_USE_FRONT, useFront)
        }
        startForegroundService(intent)

        val ip = getDeviceIp()
        currentStatusDetail = if (ip != "0.0.0.0" && !ip.startsWith("10.0.2.")) {
            val streamUrl = "http://$ip:${CameraStreamService.PORT}/stream"
            signalingClient?.notifyStreamReady(streamUrl)
            "Kamera: $streamUrl"
        } else {
            signalingClient?.notifyStreamReady("")
            "Kamera WebSocket uzerinden gonderiliyor"
        }
        streamRunning = true
        updateStatus("Kamera yayini aktif")
    }

    private fun stopCameraStream() {
        stopService(Intent(this, CameraStreamService::class.java))
        streamRunning = false
        updateStatus("Kamera yayini durduruldu")
    }

    private fun stopAllStreams() {
        stopService(Intent(this, ScreenStreamService::class.java))
        stopService(Intent(this, CameraStreamService::class.java))
        streamRunning = false
        currentStatusDetail = ""
        refreshFragments()
    }

    private suspend fun syncDeviceState() {
        val token = sessionStore.authToken()
        if (token.isBlank()) return
        backendApi.upsertDevice(token, deviceId, "phone", deviceName)
    }

    private suspend fun syncUserProfile() {
        val token = sessionStore.authToken()
        if (token.isBlank()) return

        val cached = sessionStore.address()
        if (cached.isNotBlank()) {
            currentAddress = cached
            refreshFragments()
        }

        val result = backendApi.getMe(token)
        val session = result.data ?: return
        if (session.address.isNotBlank()) {
            sessionStore.save(session)
            currentAddress = session.address
            refreshFragments()
        }
    }

    private suspend fun refreshPairings() {
        val token = sessionStore.authToken()
        if (token.isBlank()) return
        val result = backendApi.getPairings(token, deviceId)
        if (!result.error.isNullOrBlank()) {
            currentPairings = emptyList()
            currentStatusDetail = result.error
            refreshFragments()
            return
        }
        currentPairings = result.data ?: emptyList()
        if (pairedPcId != null && currentPairings.none { it.deviceId == pairedPcId }) {
            deviceIdentityStore.clearPairedPcId()
            pairedPcId = null
        }
        refreshFragments()
    }

    private fun refreshFragments() {
        accessibilityEnabled = isAccessibilityServiceEnabled()
        supportFragmentManager.fragments.forEach { fragment ->
            (fragment as? DashboardFragment)?.refreshContent()
        }
    }

    private fun isAccessibilityServiceEnabled(): Boolean {
        val serviceName = "$packageName/${ControlReceiver::class.java.name}"
        val setting = android.provider.Settings.Secure.getString(
            contentResolver,
            android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
        ) ?: return false
        return setting.contains(serviceName)
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun getDeviceIp(): String {
        if (IS_EMULATOR) return "127.0.0.1"
        return try {
            val wifiManager = applicationContext.getSystemService(WIFI_SERVICE) as android.net.wifi.WifiManager
            @Suppress("DEPRECATION")
            val wifiIp = Formatter.formatIpAddress(wifiManager.connectionInfo.ipAddress)
            if (wifiIp != "0.0.0.0") {
                wifiIp
            } else {
                val interfaces = java.util.Collections.list(java.net.NetworkInterface.getNetworkInterfaces())
                for (networkInterface in interfaces) {
                    val addresses = java.util.Collections.list(networkInterface.inetAddresses)
                    for (addr in addresses) {
                        if (!addr.isLoopbackAddress && addr is java.net.Inet4Address) {
                            return addr.hostAddress ?: "0.0.0.0"
                        }
                    }
                }
                "0.0.0.0"
            }
        } catch (_: Exception) {
            "0.0.0.0"
        }
    }

    private fun updateStatus(message: String) {
        currentStatus = message
        refreshFragments()
    }

    private fun formatAddressForUi(raw: String): String {
        val digits = raw.filter { it.isDigit() }.take(12)
        if (digits.isEmpty()) return "---- ---- ----"
        return digits.chunked(4).joinToString(" ")
    }

    override fun onResume() {
        super.onResume()
        if (sessionStore.isLoggedIn()) {
            scope.launch { refreshPairings() }
        }
        refreshFragments()
    }

    override fun onDestroy() {
        scope.cancel()
        signalingClient?.disconnect()
        super.onDestroy()
    }
}
