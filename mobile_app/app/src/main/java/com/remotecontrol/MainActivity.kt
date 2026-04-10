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
import androidx.appcompat.app.AlertDialog
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.remotecontrol.databinding.ActivityMainBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
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
    private var pairedPcAddress: String? = null
    private var currentStatus = "Baslatiliyor..."
    private var currentStatusDetail = ""
    private var currentAddress = "------------"
    private var currentPairings: List<DeviceSummary> = emptyList()
    private var streamRunning = false
    /** Bilgisayar eslesti; ekran/kamera yayini kullanici Ekrani paylas ile baslatilir. */
    private var remoteSessionPaired = false
    private var accessibilityEnabled = false
    private var connectionGeneration = 0
    /** Son device_ack partner_online (PC presence). */
    private var lastAckPartnerOnline: Boolean? = null
    /** paired geldi ama erisilebilirlik kapaliydi; kullanici ayarlardan acinca yayin dugmesi icin hazirlik. */
    private var pairingAwaitingAccessibility = false

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

        val sessionDigits = sessionStore.address().filter(Char::isDigit).take(12)
        deviceId = sessionDigits.ifBlank { deviceIdentityStore.deviceId() }
        pairedPcId = sessionStore.pairedPcId()
        pairedPcAddress = sessionStore.pairedPcAddress()
        accessibilityEnabled = isAccessibilityServiceEnabled()
        currentAddress = sessionStore.address().ifBlank { "------------" }
        updateAccessibilityHint()

        setupNavigation(savedInstanceState == null)
        requestNotificationPermission()

        scope.launch {
            syncUserProfile()
            syncDeviceState()
            refreshPairings()
        }
        connectSignaling()
    }

    fun sessionStoreRef(): SessionStore = sessionStore

    fun backendApiRef(): BackendApi = backendApi

    fun currentDeviceId(): String = deviceId

    private fun setupNavigation(initialSelect: Boolean) {
        binding.bottomNavigation.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_home -> showFragment("home") { HomeFragment() }
                R.id.nav_devices -> showFragment("devices") { DevicesFragment() }
                R.id.nav_profile -> showFragment("profile") { SettingsFragment() }
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

    fun forgetPairingFromUi(partnerDeviceId: String, partnerAddress: String?) {
        scope.launch {
            val token = sessionStore.authToken()
            if (token.isBlank()) return@launch
            val result = backendApi.deletePairing(token, deviceId, partnerDeviceId, partnerAddress)
            if (result.error.isNullOrBlank()) {
                val normalizedPartnerAddress = partnerAddress?.filter(Char::isDigit)?.take(12)
                if (pairedPcId == partnerDeviceId || (!normalizedPartnerAddress.isNullOrBlank() && pairedPcAddress == normalizedPartnerAddress)) {
                    sessionStore.clearPairedPcId()
                    sessionStore.clearPairedPcAddress()
                    pairedPcId = null
                    pairedPcAddress = null
                }
                Toast.makeText(this@MainActivity, getString(R.string.forget_pairing_success), Toast.LENGTH_SHORT).show()
                refreshPairings()
            } else {
                Toast.makeText(this@MainActivity, result.error, Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun openAccessibilitySettingsScreen() {
        Toast.makeText(this, "Dokunma kontrolu icin erisilebilirlik servisini acin.", Toast.LENGTH_LONG).show()
        startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS))
    }

    fun logout() {
        connectionGeneration += 1
        stopAllStreams()
        sessionStore.clearPairedPcId()
        sessionStore.clearPairedPcAddress()
        pairedPcId = null
        pairedPcAddress = null
        signalingClient?.disconnect(sendServerLogout = true)
        signalingClient = null
        sessionStore.clear()
        // device_id cihaza sabittir (MAC gibi); cikista silinmez.
        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }

    fun usernameText(): String = sessionStore.username().ifBlank { "Kullanici" }
        .replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }

    fun fullNameText(): String {
        val fn = sessionStore.firstName().trim()
        val ln = sessionStore.lastName().trim()
        val full = listOf(fn, ln).filter { it.isNotBlank() }.joinToString(" ")
        return full.ifBlank { usernameText() }
    }

    fun currentCodeText(): String = formatAddressForUi(currentAddress)

    fun statusText(): String = currentStatus

    fun statusDetailText(): String = currentStatusDetail

    fun currentPairings(): List<DeviceSummary> = currentPairings

    fun isAccessibilityServiceEnabledForUi(): Boolean = isAccessibilityServiceEnabled()

    fun deviceSummaryText(): String = "Bu cihaz: $deviceName"

    fun accessibilitySummaryText(): String = if (accessibilityEnabled) {
        "Erisilebilirlik servisi aktif"
    } else {
        "Dokunma kontrolu icin erisilebilirlik servisini acin"
    }

    /** PC oturumu kapandi; telefon signaling'e bagli kalir, yeniden baglanti yalnizca masaustunden. */
    private fun handlePeerSessionEnded() {
        if (isFinishing || isDestroyed) return
        Log.i(TAG, "PC oturumu sona erdi — yayin durduruldu, WS acik")
        stopAllStreams()
        remoteSessionPaired = false
        pairingAwaitingAccessibility = false
        currentStatus = "Bilgisayar baglantisi kesildi"
        currentStatusDetail = "Oturumu masaustu uygulamasindan yeniden baslatin; telefon sabit adreste bekliyor."
        refreshFragments()
    }

    /** Soket koptu; oturumu yeniden kurmak icin (kullanici arayuzunden degil, transport). */
    private fun reconnectSignalingTransport() {
        if (isFinishing || isDestroyed || !sessionStore.isLoggedIn()) return
        Log.w(TAG, "Signaling soketi koptu — transport yenileniyor")
        stopAllStreams()
        remoteSessionPaired = false
        pairingAwaitingAccessibility = false
        currentStatus = "Baglanti kesildi"
        currentStatusDetail = "Sunucuya yeniden baglaniliyor..."
        refreshFragments()
        signalingClient?.disconnect(sendServerLogout = false)
        signalingClient = null
        connectSignaling()
    }

    /**
     * Erisilebilirlik yeni acildiginda: sunucudaki eski WS / kod oturumu kalintilarini temizlemek icin
     * device_logout + sifir SignalingClient ile yeniden baglanir. PC tarafinda tekrar join gerekir.
     */
    private fun restartSignalingAfterAccessibilityOpened() {
        if (isFinishing || isDestroyed || !sessionStore.isLoggedIn()) return
        Log.i(TAG, "Erisilebilirlik acildi — signaling sifirlaniyor (temiz hat)")
        streamRunning = false
        remoteSessionPaired = false
        pairingAwaitingAccessibility = false
        stopAllStreams()
        currentStatus = "Erisilebilirlik hazir"
        currentStatusDetail = "Baglanti yenilendi; bilgisayardan tekrar eslestirin."
        refreshFragments()
        signalingClient?.disconnect(sendServerLogout = true)
        signalingClient = null
        connectSignaling()
        scope.launch {
            delay(500)
            runOnUiThread {
                signalingClient?.pushAccessibilityToServer()
            }
        }
        Toast.makeText(this, "Erisilebilirlik icin baglanti sifirlandi.", Toast.LENGTH_SHORT).show()
    }

    private fun connectSignaling() {
        val generation = ++connectionGeneration
        lastAckPartnerOnline = null
        remoteSessionPaired = false
        pairingAwaitingAccessibility = false
        currentStatus = "Signaling sunucusuna baglaniyor"
        currentStatusDetail = ""
        refreshFragments()

        signalingClient?.disconnect(sendServerLogout = false)
        val clientRef = arrayOfNulls<SignalingClient>(1)
        val client = SignalingClient(
            serverUrl = SIGNALING_URL,
            deviceId = deviceId,
            deviceAddress = currentAddress.filter(Char::isDigit).take(12),
            isAccessibilityEnabled = { isAccessibilityServiceEnabled() },
            onPaired = { _, partnerDeviceId ->
                runOnUiThread {
                    if (generation != connectionGeneration || signalingClient !== clientRef[0]) return@runOnUiThread
                    if (!partnerDeviceId.isNullOrBlank()) {
                        onFirstPairComplete(partnerDeviceId)
                    }
                    updateAccessibilityHint()
                    if (!isAccessibilityServiceEnabled()) {
                        pairingAwaitingAccessibility = true
                        remoteSessionPaired = false
                        streamRunning = false
                        currentStatus = "Erisilebilirlik kapali"
                        currentStatusDetail = "Kontrol icin erisilebilirlik servisini acin."
                        refreshFragments()
                        // Desktop'a hata mesaji gonder ki oturum ekranindan ciksin
                        signalingClient?.sendAccessibilityError()
                        showAccessibilityRequiredDialog()
                        return@runOnUiThread
                    }
                    pairingAwaitingAccessibility = false
                    remoteSessionPaired = true
                    streamRunning = false
                    scope.launch { refreshPairings() }
                    currentStatus = getString(R.string.pair_pc_connected_title)
                    currentStatusDetail = getString(R.string.pair_start_broadcast_hint)
                    refreshFragments()
                    // Ekran paylasimi masaustunden (screen_capture_on) baslatilir.
                }
            },
            onPairedDevicesStatus = { pairedDeviceIds, onlineDeviceIds, partnerOnline ->
                runOnUiThread {
                    if (generation != connectionGeneration || signalingClient !== clientRef[0]) return@runOnUiThread
                    applyRealtimePairingStatus(pairedDeviceIds, onlineDeviceIds, partnerOnline)
                }
            },
            onCommand = { action, params -> handleCommand(action, params) },
            onPeerSessionEnded = {
                runOnUiThread {
                    if (generation != connectionGeneration || signalingClient !== clientRef[0]) return@runOnUiThread
                    handlePeerSessionEnded()
                }
            },
            onTransportDisconnected = {
                runOnUiThread {
                    if (generation != connectionGeneration || signalingClient !== clientRef[0]) return@runOnUiThread
                    reconnectSignalingTransport()
                }
            },
        )
        clientRef[0] = client
        signalingClient = client
        signalingClient?.connect()
        currentStatus = "Cevrimici; baglanti bilgisayardan baslatilir"
        currentStatusDetail = "Sabit adres: $currentAddress"
        refreshFragments()
        Log.i(TAG, "Device address: $currentAddress")
    }

    private fun onFirstPairComplete(pcDeviceId: String) {
        if (pcDeviceId.isBlank()) return
        sessionStore.savePairedPcId(pcDeviceId)
        pairedPcId = pcDeviceId
        currentPairings.firstOrNull {
            (!pairedPcAddress.isNullOrBlank() && it.address == pairedPcAddress) || it.deviceId == pcDeviceId
        }?.address?.let {
            sessionStore.savePairedPcAddress(it)
            pairedPcAddress = it
        }
        signalingClient?.sendPairConfirm(pcDeviceId)
        refreshFragments()
        Log.i(TAG, "Pair confirmed with PC: $pcDeviceId")
    }

    private fun applyRealtimePairingStatus(
        pairedDeviceIds: List<String>,
        onlineDeviceIds: List<String>,
        partnerOnlineFromAck: Boolean,
    ) {
        val pairedSet = pairedDeviceIds.toSet()
        val onlineSet = onlineDeviceIds.toSet()
        val pcNorm = pairedPcId?.filter { it.isDigit() }?.take(12).orEmpty()
        val prevPartnerOnline = lastAckPartnerOnline
        lastAckPartnerOnline = partnerOnlineFromAck
        if (prevPartnerOnline == true && !partnerOnlineFromAck && pcNorm.isNotEmpty()) {
            val pcStillListed = pairedDeviceIds.any { it.filter { ch -> ch.isDigit() }.take(12) == pcNorm }
            if (pcStillListed && (remoteSessionPaired || streamRunning)) {
                handlePeerSessionEnded()
                return
            }
        }
        runOnUiThread {
            if (pairedSet.isEmpty() && onlineSet.isEmpty()) {
                scope.launch { refreshPairings() }
                return@runOnUiThread
            }
            if (pairedSet.isNotEmpty() && currentPairings.isNotEmpty()) {
                currentPairings = currentPairings
                    .map { d ->
                        if (d.deviceId in pairedSet) d.copy(online = d.deviceId in onlineSet) else d
                    }
                    .sortedWith(
                        compareByDescending<DeviceSummary> { it.online }
                            .thenBy { it.deviceName ?: "" }
                            .thenBy { it.address ?: "" },
                    )
                refreshFragments()
            }
            scope.launch { refreshPairings() }
        }
    }

    private fun handleCommand(action: String, params: Map<String, Any>) {
        when (action) {
            "touch" -> {
                val x = (params["x"] as? Number)?.toFloat() ?: return
                val y = (params["y"] as? Number)?.toFloat() ?: return
                runOnUiThread {
                    withControlReceiver("Dokunma komutu") { performTouch(x, y) }
                }
            }
            "swipe" -> {
                val x1 = (params["x1"] as? Number)?.toFloat() ?: return
                val y1 = (params["y1"] as? Number)?.toFloat() ?: return
                val x2 = (params["x2"] as? Number)?.toFloat() ?: return
                val y2 = (params["y2"] as? Number)?.toFloat() ?: return
                runOnUiThread {
                    withControlReceiver("Kaydirma komutu") { performSwipe(x1, y1, x2, y2) }
                }
            }
            "key_event" -> {
                val keyCode = (params["key_code"] as? Number)?.toInt() ?: return
                runOnUiThread {
                    withControlReceiver("Tus komutu") { performKeyEvent(keyCode) }
                }
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
            "screen_capture_on" -> runOnUiThread { startScreenShareFromRemote() }
            "camera_on" -> runOnUiThread { requestCameraAccess(useFront = false) }
            "camera_off" -> runOnUiThread { stopCameraStreamFromPc() }
            else -> Log.w(TAG, "Unknown command: $action")
        }
    }

    private fun requestScreenCapture() {
        val projectionManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjectionLauncher.launch(projectionManager.createScreenCaptureIntent())
    }

    /** Masaustunden gelen komut: eslestirme ve erisilebilirlik sonrasi ekran (veya emulatorda kamera) paylasimi. */
    private fun startScreenShareFromRemote() {
        if (!remoteSessionPaired) {
            Log.w(TAG, "screen_capture_on yok sayildi: oturum eslesmemis")
            return
        }
        if (!isAccessibilityServiceEnabled()) {
            pairingAwaitingAccessibility = true
            currentStatus = "Erisilebilirlik kapali"
            currentStatusDetail = "Ekran paylasimi icin erisilebilirligi acin; ardindan bilgisayardan tekrar baglanin."
            refreshFragments()
            signalingClient?.sendAccessibilityError()
            showAccessibilityRequiredDialog()
            return
        }
        if (streamRunning) return
        if (IS_EMULATOR) {
            updateStatus(getString(R.string.pair_camera_starting_hint))
            requestCameraAccess(useFront = false)
        } else {
            updateStatus(getString(R.string.pair_screen_permission_hint))
            requestScreenCapture()
        }
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

    /** Yalnizca masaustu camera_off komutu; telefon arayuzunde durdurma yok. */
    private fun stopCameraStreamFromPc() {
        stopService(Intent(this, CameraStreamService::class.java))
        streamRunning = false
        currentStatusDetail = ""
        updateStatus("Kamera yayini masaustunden durduruldu")
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
        val result = backendApi.upsertDevice(
            token,
            deviceId,
            "phone",
            deviceName,
            HardwareFingerprint.macOrAndroidId(this),
        )
        result.data
            ?.filter(Char::isDigit)
            ?.take(12)
            ?.takeIf { it.isNotBlank() }
            ?.let { address ->
                deviceId = address
                deviceIdentityStore.saveDeviceId(address)
                currentAddress = address
                sessionStore.save(sessionStore.userId().let { currentUserId ->
                    AuthSession(token, currentUserId, sessionStore.username(), address)
                })
                refreshFragments()
            }
    }

    private suspend fun syncUserProfile() {
        val token = sessionStore.authToken()
        if (token.isBlank()) return

        val cached = sessionStore.address()
        if (cached.isNotBlank()) {
            currentAddress = cached
            refreshFragments()
        }

        val profile = backendApi.getProfile(token, deviceId)
        profile.data?.let { p ->
            sessionStore.saveProfile(p.firstName, p.lastName, p.email, p.phone)
        }

        val result = backendApi.getMe(token, deviceId)
        val session = result.data ?: return
        if (session.address.isNotBlank()) {
            deviceId = session.address.filter(Char::isDigit).take(12)
            deviceIdentityStore.saveDeviceId(deviceId)
            sessionStore.save(session)
            currentAddress = session.address
            refreshFragments()
        }
    }

    private suspend fun refreshPairings() {
        val token = sessionStore.authToken()
        if (token.isBlank()) return
        val devicesResult = backendApi.getDevices(token)
        val recentResult = backendApi.getRecentDevices(token, "pc")
        val pairingsResult = backendApi.getPairings(token, deviceId)
        if (!devicesResult.error.isNullOrBlank() && !recentResult.error.isNullOrBlank() && !pairingsResult.error.isNullOrBlank()) {
            currentPairings = emptyList()
            currentStatusDetail = pairingsResult.error.orEmpty()
            refreshFragments()
            return
        }

        val merged = LinkedHashMap<String, DeviceSummary>()
        (devicesResult.data ?: emptyList())
            .filter { it.deviceId != deviceId }
            .forEach {
                val key = it.address?.filter(Char::isDigit)?.take(12).orEmpty().ifBlank { it.deviceId }
                merged[key] = it.copy(address = it.address?.filter(Char::isDigit)?.take(12))
            }
        (recentResult.data ?: emptyList())
            .filter { it.deviceId != deviceId }
            .forEach { device ->
                val normalizedAddress = device.address?.filter(Char::isDigit)?.take(12)
                val key = normalizedAddress.orEmpty().ifBlank { device.deviceId }
                val existing = merged[key]
                merged[key] = if (existing == null) {
                    device.copy(address = normalizedAddress)
                } else {
                    existing.copy(
                        deviceName = existing.deviceName ?: device.deviceName,
                        address = existing.address ?: normalizedAddress,
                        online = existing.online || device.online,
                    )
                }
            }
        (pairingsResult.data ?: emptyList())
            .filter { it.deviceId != deviceId }
            .forEach { device ->
                val normalizedAddress = device.address?.filter(Char::isDigit)?.take(12)
                val key = normalizedAddress.orEmpty().ifBlank { device.deviceId }
                val existing = merged[key]
                merged[key] = if (existing == null) {
                    device.copy(address = normalizedAddress)
                } else {
                    existing.copy(
                        deviceName = existing.deviceName ?: device.deviceName,
                        address = existing.address ?: normalizedAddress,
                        online = existing.online || device.online,
                    )
                }
            }

        currentPairings = merged.values
            .sortedWith(
                compareByDescending<DeviceSummary> { it.online }
                    .thenBy { it.deviceName ?: "" }
                    .thenBy { it.address ?: "" }
            )
        if (pairedPcId != null && currentPairings.none { it.deviceId == pairedPcId && it.deviceType == "pc" }) {
            sessionStore.clearPairedPcId()
            pairedPcId = null
        }
        val matchedPreferred = currentPairings.firstOrNull {
            it.deviceType == "pc" && (
                (pairedPcId != null && it.deviceId == pairedPcId) ||
                    (!pairedPcAddress.isNullOrBlank() && it.address == pairedPcAddress)
            )
        }
        if (matchedPreferred?.address.isNullOrBlank()) {
            if (!pairedPcAddress.isNullOrBlank() && currentPairings.none { it.address == pairedPcAddress && it.deviceType == "pc" }) {
                sessionStore.clearPairedPcAddress()
                pairedPcAddress = null
            }
        } else {
            val normalizedAddress = matchedPreferred?.address?.filter(Char::isDigit)?.take(12).orEmpty()
            sessionStore.savePairedPcAddress(normalizedAddress)
            pairedPcAddress = normalizedAddress
        }
        refreshFragments()
    }

    private fun showAccessibilityRequiredDialog() {
        AlertDialog.Builder(this)
            .setTitle("Erisilebilirlik gerekli")
            .setMessage("Bilgisayardan kontrol edebilmek icin Erisilebilirlik servisini acman gerekiyor. Ayarlara gidelim mi?")
            .setPositiveButton("Ayarlari ac") { _, _ ->
                openAccessibilitySettingsScreen()
            }
            .setNegativeButton("Vazgec", null)
            .show()
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

    private fun withControlReceiver(actionLabel: String, block: ControlReceiver.() -> Boolean) {
        val receiver = ControlReceiver.instance
        if (receiver == null) {
            currentStatus = "$actionLabel uygulanamadi"
            currentStatusDetail = "Erisilebilirlik servisini acin ve tekrar deneyin."
            refreshFragments()
            openAccessibilitySettingsScreen()
            return
        }
        val success = receiver.block()
        if (!success) {
            currentStatus = "$actionLabel uygulanamadi"
            currentStatusDetail = "Android erisilebilirlik servisi komutu reddetti."
            refreshFragments()
        }
    }

    private fun updateAccessibilityHint() {
        accessibilityEnabled = isAccessibilityServiceEnabled()
        if (!accessibilityEnabled) {
            if (currentStatusDetail.isBlank() || currentStatusDetail.contains("Erisilebilirlik", ignoreCase = true)) {
                currentStatusDetail = "Kontrol icin Erisilebilirlik ayarlarini acin."
            }
        }
    }

    private fun formatAddressForUi(raw: String): String {
        val digits = raw.filter { it.isDigit() }.take(12)
        if (digits.isEmpty()) return "---- ---- ----".replace(" ", "-")
        return digits.chunked(4).joinToString("-")
    }

    override fun onResume() {
        super.onResume()
        val nowA11y = isAccessibilityServiceEnabled()
        val hadA11y = accessibilityEnabled
        if (sessionStore.isLoggedIn() && nowA11y && !hadA11y) {
            if (pairingAwaitingAccessibility) {
                // Mevcut oturumu KORU — signaling sifirlanmasin!
                // Sadece durumu guncelle; oturum canli kaliyor.
                Log.i(TAG, "Erisilebilirlik acildi — mevcut oturum korunuyor")
                pairingAwaitingAccessibility = false
                remoteSessionPaired = true
                accessibilityEnabled = true
                currentStatus = getString(R.string.pair_pc_connected_title)
                currentStatusDetail = getString(R.string.pair_start_broadcast_hint)
                refreshFragments()
                signalingClient?.pushAccessibilityToServer()
                Toast.makeText(this, "Erisilebilirlik aktif — bilgisayardan tekrar baglanin.", Toast.LENGTH_SHORT).show()
            } else {
                restartSignalingAfterAccessibilityOpened()
            }
        }
        updateAccessibilityHint()
        if (sessionStore.isLoggedIn()) {
            if (pairingAwaitingAccessibility && isAccessibilityServiceEnabled() && !streamRunning) {
                pairingAwaitingAccessibility = false
                remoteSessionPaired = true
                currentStatus = getString(R.string.pair_pc_connected_title)
                currentStatusDetail = getString(R.string.pair_start_broadcast_hint)
            }
            scope.launch { refreshPairings() }
        }
        refreshFragments()
        signalingClient?.pushAccessibilityToServer()
    }

    override fun onDestroy() {
        connectionGeneration += 1
        scope.cancel()
        signalingClient?.disconnect(sendServerLogout = false)
        signalingClient = null
        super.onDestroy()
    }
}
