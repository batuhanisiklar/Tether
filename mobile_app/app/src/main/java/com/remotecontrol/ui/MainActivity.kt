package com.remotecontrol.ui

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.remotecontrol.R
import com.remotecontrol.auth.AppSettingsStore
import com.remotecontrol.auth.LoginActivity
import com.remotecontrol.auth.SessionStore
import com.remotecontrol.data.AuthSession
import com.remotecontrol.data.BackendApi
import com.remotecontrol.data.DeviceIdentityStore
import com.remotecontrol.data.DeviceSummary
import com.remotecontrol.data.UserProfile
import com.remotecontrol.device.HardwareFingerprint
import com.remotecontrol.network.SignalingClient
import com.remotecontrol.service.CameraStreamService
import com.remotecontrol.service.ControlReceiver
import com.remotecontrol.service.ScreenStreamService
import com.remotecontrol.databinding.ActivityMainBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity() {
    data class ClearPairingsResult(
        val total: Int,
        val cleared: Int,
        val failed: Int,
    )

    companion object {
        private const val TAG = "MainActivity"
        const val SIGNALING_URL = "wss://connect-your-phone.onrender.com"
        private const val EVENT_CHANNEL_ID = "app_events_channel"
        private const val EVENT_NOTIFICATION_ID_CONNECTED = 3101
        private const val EVENT_NOTIFICATION_ID_DISCONNECTED = 3102

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
    private lateinit var appSettingsStore: AppSettingsStore
    private lateinit var deviceIdentityStore: DeviceIdentityStore
    private lateinit var backendApi: BackendApi

    private var signalingClient: SignalingClient? = null
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private lateinit var deviceId: String
    private val deviceName: String by lazy { buildDeviceName() }
    private var pairedPcId: String? = null
    private var pairedPcAddress: String? = null
    private var currentStatus = "Başlatılıyor…"
    private var currentStatusDetail = ""
    private var currentAddress = "------------"
    private var currentPairings: List<DeviceSummary> = emptyList()
    private val recentEvents: ArrayDeque<Pair<Long, String>> = ArrayDeque()
    private var streamRunning = false
    /** MediaProjection sistem diyalogu acikken tekrar launch edilmesini engeller */
    private var awaitingMediaProjectionConsent = false
    /** Bilgisayar eslesti; ekran/kamera yayini kullanici Ekrani paylas ile baslatilir. */
    private var remoteSessionPaired = false
    private var accessibilityEnabled = false
    private var connectionGeneration = 0
    /** Son device_ack partner_online (PC presence). */
    private var lastAckPartnerOnline: Boolean? = null
    /** Gecici partner_online=false dalgalanmalari icin tolerans sayaci. */
    private var partnerOfflineAckStreak = 0
    /** paired geldi ama erisilebilirlik kapaliydi; kullanici ayarlardan acinca yayin dugmesi icin hazirlik. */
    private var pairingAwaitingAccessibility = false
    /** Erisilebilirlik ayarina gecis akisi aktifken zorla one getirmeyi engeller. */
    private var openingAccessibilitySettings = false
    /** Panelden gelen son mutlak ekran rotasyonu: 0, 90, 180, 270. */
    private var remoteRotationDegrees = 0
    private var hasRemoteRotationOverride = false

    private val mediaProjectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        awaitingMediaProjectionConsent = false
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            startScreenStream(result.resultCode, result.data!!)
        } else {
            updateStatus(getString(R.string.status_screen_permission_denied))
            addRecentEvent(getString(R.string.event_screen_permission_denied))
        }
    }

    private val cameraPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            startCameraStream(useFront = false)
        } else {
            updateStatus(getString(R.string.status_camera_permission_denied))
            addRecentEvent(getString(R.string.event_camera_permission_denied))
        }
    }

    private var isAudioEnabledForStream = false

    private val audioPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        isAudioEnabledForStream = granted
        launchMediaProjectionDialog()
    }

    private val notifPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT

        sessionStore = SessionStore(this)
        appSettingsStore = AppSettingsStore(this)
        deviceIdentityStore = DeviceIdentityStore(this)
        backendApi = BackendApi(SIGNALING_URL)

        if (!sessionStore.isLoggedIn()) {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        createEventNotificationChannel()

        val sessionDigits = sessionStore.address().filter(Char::isDigit).take(12)
        deviceId = sessionDigits.ifBlank { deviceIdentityStore.deviceId() }
        pairedPcId = sessionStore.pairedPcId()
        pairedPcAddress = sessionStore.pairedPcAddress()
        accessibilityEnabled = isAccessibilityServiceEnabled()
        currentAddress = sessionStore.address().ifBlank { "------------" }
        updateAccessibilityHint()
        addRecentEvent(getString(R.string.event_app_opened))

        setupNavigation(savedInstanceState == null)
        requestNotificationPermission()

        scope.launch {
            syncDeviceState()
            syncUserProfile()
            refreshPairings()
            if (!isFinishing && !isDestroyed && sessionStore.isLoggedIn()) {
                connectSignaling()
            }
        }
    }

    fun sessionStoreRef(): SessionStore = sessionStore

    fun appSettingsStoreRef(): AppSettingsStore = appSettingsStore

    fun backendApiRef(): BackendApi = backendApi

    fun currentDeviceId(): String = deviceId

    private fun setupNavigation(initialSelect: Boolean) {
        binding.bottomNavigation.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_home -> showFragment("home") { HomeFragment() }
                R.id.nav_devices -> showFragment("devices") { DevicesFragment() }
                R.id.nav_help -> showFragment("help") { HelpFragment() }
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

    fun openHelpTab() {
        binding.bottomNavigation.selectedItemId = R.id.nav_help
    }

    fun openDevicesTab() {
        binding.bottomNavigation.selectedItemId = R.id.nav_devices
    }

    fun forgetPairingFromUi(partnerDeviceId: String, partnerAddress: String?) {
        scope.launch {
            val token = sessionStore.authToken()
            if (token.isBlank()) return@launch
            val result = backendApi.deletePairing(token, deviceId, partnerDeviceId, partnerAddress)
            if (result.error.isNullOrBlank()) {
                val normalizedPartnerAddress = partnerAddress?.filter(Char::isDigit)?.take(12)
                currentPairings = currentPairings.filterNot { d ->
                    d.deviceId == partnerDeviceId ||
                        (!normalizedPartnerAddress.isNullOrBlank() && d.address == normalizedPartnerAddress)
                }
                refreshFragments()
                if (pairedPcId == partnerDeviceId || (!normalizedPartnerAddress.isNullOrBlank() && pairedPcAddress == normalizedPartnerAddress)) {
                    sessionStore.clearPairedPcId()
                    sessionStore.clearPairedPcAddress()
                    pairedPcId = null
                    pairedPcAddress = null
                }
                Toast.makeText(this@MainActivity, getString(R.string.forget_pairing_success), Toast.LENGTH_SHORT).show()
                addRecentEvent(getString(R.string.event_pairing_removed))
                refreshPairings()
            } else {
                Toast.makeText(this@MainActivity, result.error, Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun openAccessibilitySettingsScreen() {
        openingAccessibilitySettings = true
        Toast.makeText(this, getString(R.string.toast_open_accessibility_needed), Toast.LENGTH_LONG).show()
        startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS))
    }

    fun startScreenShareFromUi() {
        if (!remoteSessionPaired) {
            Toast.makeText(this, getString(R.string.pair_start_broadcast_hint), Toast.LENGTH_SHORT).show()
            return
        }
        if (streamRunning) return
        requestScreenCapture()
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
        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }

    fun usernameText(): String = sessionStore.username().ifBlank { "Kullanıcı" }
        .replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }

    fun homeUserDisplayText(): String {
        return fullNameText()
    }

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

    fun pairedPcCount(): Int = currentPairings.count { it.deviceType == "pc" }

    fun recentEventLines(limit: Int = 3): List<String> {
        val formatter = SimpleDateFormat("HH:mm", Locale("tr", "TR"))
        return recentEvents
            .take(limit)
            .map { (timeMs, message) ->
                "${formatter.format(Date(timeMs))} • $message"
            }
    }

    fun isAccessibilityServiceEnabledForUi(): Boolean = isAccessibilityServiceEnabled()

    fun deviceSummaryText(): String = getString(R.string.device_summary_template, deviceName)

    fun accessibilitySummaryText(): String = if (accessibilityEnabled) {
        getString(R.string.accessibility_summary_enabled)
    } else {
        getString(R.string.accessibility_summary_disabled)
    }

    /** PC oturumu kapandi; telefon signaling'e bagli kalir, yeniden baglanti yalnizca masaustunden. */
    private fun handlePeerSessionEnded() {
        if (isFinishing || isDestroyed) return
        Log.i(TAG, "PC oturumu sona erdi - yayın durduruldu, WS açık")
        stopAllStreams()
        remoteSessionPaired = false
        hasRemoteRotationOverride = false
        remoteRotationDegrees = 0
        pairingAwaitingAccessibility = false
        currentStatus = getString(R.string.status_peer_disconnected_title)
        currentStatusDetail = getString(R.string.status_peer_disconnected_detail)
        addRecentEvent(getString(R.string.event_peer_session_ended))
        notifyDisconnectedIfEnabled(currentStatusDetail)
        navigateToHomeAfterDisconnect()
        refreshFragments()
    }

    /** Soket koptu; oturumu yeniden kurmak icin (kullanici arayuzunden degil, transport). */
    private fun reconnectSignalingTransport() {
        if (isFinishing || isDestroyed || !sessionStore.isLoggedIn()) return
        Log.w(TAG, "Signaling soketi koptu - transport yenileniyor")
        stopAllStreams()
        remoteSessionPaired = false
        pairingAwaitingAccessibility = false
        currentStatus = getString(R.string.status_connection_lost_title)
        currentStatusDetail = getString(R.string.status_connection_lost_detail)
        addRecentEvent(getString(R.string.event_transport_reconnecting))
        notifyDisconnectedIfEnabled(currentStatusDetail)
        navigateToHomeAfterDisconnect()
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
        Log.i(TAG, "Erişilebilirlik açıldı - signaling sıfırlanıyor (temiz hat)")
        streamRunning = false
        remoteSessionPaired = false
        pairingAwaitingAccessibility = false
        stopAllStreams()
        currentStatus = getString(R.string.status_accessibility_ready_title)
        currentStatusDetail = getString(R.string.status_accessibility_ready_detail)
        addRecentEvent(getString(R.string.event_accessibility_reconnected))
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
        Toast.makeText(this, getString(R.string.toast_accessibility_connection_reset), Toast.LENGTH_SHORT).show()
    }

    private fun connectSignaling() {
        val token = sessionStore.authToken()
        val address = currentAddress.filter(Char::isDigit).take(12)
        val ownDeviceId = deviceId.filter(Char::isDigit).take(12)
        if (token.isBlank() || ownDeviceId.length != 12 || address.length != 12) {
            currentStatus = getString(R.string.status_address_not_ready_title)
            currentStatusDetail = getString(R.string.status_address_not_ready_detail)
            addRecentEvent(getString(R.string.event_address_not_ready))
            refreshFragments()
            return
        }
        deviceId = ownDeviceId
        currentAddress = address
        val generation = ++connectionGeneration
        lastAckPartnerOnline = null
        partnerOfflineAckStreak = 0
        remoteSessionPaired = false
        pairingAwaitingAccessibility = false
        currentStatus = getString(R.string.status_signaling_connecting)
        currentStatusDetail = ""
        refreshFragments()

        signalingClient?.disconnect(sendServerLogout = false)
        val clientRef = arrayOfNulls<SignalingClient>(1)
        val client = SignalingClient(
            serverUrl = SIGNALING_URL,
            authToken = token,
            deviceId = ownDeviceId,
            deviceAddress = address,
            isAccessibilityEnabled = { isAccessibilityServiceEnabled() },
            isMediaMuted = { currentMediaMutedState() },
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
                        currentStatus = getString(R.string.status_accessibility_off_title)
                        currentStatusDetail = getString(R.string.status_accessibility_off_detail)
                        refreshFragments()
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
                    addRecentEvent(getString(R.string.event_pc_connected))
                    notifyConnectedIfEnabled()
                    refreshFragments()
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
        currentStatus = getString(R.string.status_online_waiting_pc_title)
        currentStatusDetail = getString(R.string.status_online_waiting_pc_detail, currentAddress)
        addRecentEvent(getString(R.string.event_waiting_for_pc))
        refreshFragments()
        Log.i(TAG, "Device address: $currentAddress")
    }

    private fun currentMediaMutedState(): Boolean? {
        return try {
            val am = getSystemService(AUDIO_SERVICE) as? AudioManager ?: return null
            val volume = am.getStreamVolume(AudioManager.STREAM_MUSIC)
            val muted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                am.isStreamMute(AudioManager.STREAM_MUSIC)
            } else {
                volume <= 0
            }
            muted || volume <= 0
        } catch (_: Exception) {
            null
        }
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
        addRecentEvent(getString(R.string.event_pair_confirmed))
        refreshFragments()
        Log.i(TAG, "Pair confirmed with PC: $pcDeviceId")
    }

    /**
     * Bilgisayar oturumu bittiğinde (veya transport koptuğunda) kullanıcıyı ana ekrana geri al.
     * Yayın sırasında `moveTaskToBack(true)` ile arka plana atılmış olabilir; bu yüzden activity'yi öne getiriyoruz.
     */
    private fun navigateToHomeAfterDisconnect() {
        if (openingAccessibilitySettings) {
            Log.i(TAG, "A11y ayari acik; disconnect sonrasi bring-to-front atlandi")
            return
        }
        try {
            val intent = Intent(this, MainActivity::class.java).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP or
                    Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP,
                )
            }
            startActivity(intent)
        } catch (e: Exception) {
            Log.w(TAG, "Disconnect redirect bring-to-front failed", e)
        }
        runOnUiThread {
            try {
                if (::binding.isInitialized && binding.bottomNavigation.selectedItemId != R.id.nav_home) {
                    binding.bottomNavigation.selectedItemId = R.id.nav_home
                }
            } catch (e: Exception) {
                Log.w(TAG, "Disconnect redirect nav failed", e)
            }
        }
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
        if (partnerOnlineFromAck) {
            partnerOfflineAckStreak = 0
        } else if (prevPartnerOnline == true) {
            partnerOfflineAckStreak = 1
        } else if (!partnerOnlineFromAck && partnerOfflineAckStreak > 0) {
            partnerOfflineAckStreak += 1
        }
        if (prevPartnerOnline == true && !partnerOnlineFromAck && pcNorm.isNotEmpty()) {
            val pcStillListed = pairedDeviceIds.any { it.filter { ch -> ch.isDigit() }.take(12) == pcNorm }
            if (pcStillListed && (remoteSessionPaired || streamRunning) && partnerOfflineAckStreak >= 2) {
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
                    withControlReceiver(getString(R.string.command_touch)) { performTouch(x, y) }
                }
            }
            "swipe" -> {
                val x1 = (params["x1"] as? Number)?.toFloat() ?: return
                val y1 = (params["y1"] as? Number)?.toFloat() ?: return
                val x2 = (params["x2"] as? Number)?.toFloat() ?: return
                val y2 = (params["y2"] as? Number)?.toFloat() ?: return
                runOnUiThread {
                    withControlReceiver(getString(R.string.command_swipe)) { performSwipe(x1, y1, x2, y2) }
                }
            }
            "key_event" -> {
                val keyCode = (params["key_code"] as? Number)?.toInt() ?: return
                runOnUiThread {
                    withControlReceiver(getString(R.string.command_key)) { performKeyEvent(keyCode) }
                }
            }
            "rotate_screen" -> {
                val degrees = normalizeRotationDegrees((params["degrees"] as? Number)?.toInt() ?: 0)
                runOnUiThread {
                    if (isDestroyed || isFinishing) return@runOnUiThread
                    remoteRotationDegrees = degrees
                    hasRemoteRotationOverride = true
                    ScreenStreamService.instance?.setRemoteRotationDegrees(degrees)
                    if (!streamRunning) {
                        requestedOrientation = orientationForDegrees(degrees)
                        Log.i(TAG, "rotate_screen applied: ${degrees}deg orientation=$requestedOrientation")
                        refreshScreenStreamRotationSoon()
                    } else {
                        Log.i(TAG, "rotate_screen applied to stream metadata: ${degrees}deg")
                    }
                }
            }
            "screen_capture_on" -> runOnUiThread { startScreenShareFromRemote() }
            "camera_on" -> runOnUiThread { requestCameraAccess(useFront = false) }
            "camera_off" -> runOnUiThread { stopCameraStreamFromPc() }
            "paste_text" -> {
                val raw = params["text"]
                val text = when (raw) {
                    is String -> raw
                    else -> raw?.toString() ?: ""
                }
                if (text.isBlank()) return
                runOnUiThread {
                    withControlReceiver(getString(R.string.command_paste)) { performPasteText(text) }
                }
            }
            else -> Log.w(TAG, "Unknown command: $action")
        }
    }

    private fun normalizeRotationDegrees(degrees: Int): Int {
        val normalized = ((degrees % 360) + 360) % 360
        return ((normalized + 45) / 90 * 90) % 360
    }

    private fun orientationForDegrees(degrees: Int): Int {
        return when (normalizeRotationDegrees(degrees)) {
            90 -> ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            180 -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT
            270 -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE
            else -> ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
    }

    private fun refreshScreenStreamRotationSoon() {
        scope.launch {
            delay(350)
            ScreenStreamService.instance?.refreshRotationFromRemote()
            delay(700)
            ScreenStreamService.instance?.refreshRotationFromRemote()
        }
    }

    private fun requestScreenCapture() {
        if (awaitingMediaProjectionConsent) {
            Log.i(TAG, "MediaProjection izni zaten bekleniyor - diyalog tekrar açılmıyor")
            return
        }
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                isAudioEnabledForStream = true
                launchMediaProjectionDialog()
            } else {
                audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
            }
        } else {
            isAudioEnabledForStream = false
            launchMediaProjectionDialog()
        }
    }

    private fun launchMediaProjectionDialog() {
        awaitingMediaProjectionConsent = true
        val projectionManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            val config = android.media.projection.MediaProjectionConfig.createConfigForDefaultDisplay()
            projectionManager.createScreenCaptureIntent(config)
        } else {
            projectionManager.createScreenCaptureIntent()
        }
        mediaProjectionLauncher.launch(intent)
    }

    /** Masaustunden gelen komut: eslestirme ve erisilebilirlik sonrasi ekran paylasimi. */
    private fun startScreenShareFromRemote() {
        if (!remoteSessionPaired) {
            Log.w(TAG, "screen_capture_on yok sayildi: oturum eslesmemis")
            return
        }
        if (!isAccessibilityServiceEnabled()) {
            pairingAwaitingAccessibility = true
            currentStatus = getString(R.string.status_accessibility_off_title)
            currentStatusDetail = getString(R.string.status_accessibility_required_share_detail)
            refreshFragments()
            signalingClient?.sendAccessibilityError()
            showAccessibilityRequiredDialog()
            return
        }
        if (streamRunning) return
        updateStatus(getString(R.string.pair_screen_permission_hint))
        requestScreenCapture()
    }

    private fun startScreenStream(resultCode: Int, data: Intent) {
        val intent = Intent(this, ScreenStreamService::class.java).apply {
            putExtra(ScreenStreamService.EXTRA_RESULT_CODE, resultCode)
            putExtra(ScreenStreamService.EXTRA_RESULT_DATA, data)
            putExtra("EXTRA_AUDIO_ENABLED", isAudioEnabledForStream)
            putExtra(ScreenStreamService.EXTRA_REMOTE_ROTATION_ENABLED, hasRemoteRotationOverride)
            putExtra(ScreenStreamService.EXTRA_REMOTE_ROTATION_DEGREES, remoteRotationDegrees)
        }
        startForegroundService(intent)

        currentStatusDetail = getString(R.string.status_screen_streaming_detail)
        streamRunning = true
        updateStatus(getString(R.string.status_screen_streaming_title))
        addRecentEvent(getString(R.string.event_screen_stream_started))

        moveTaskToBack(true)
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

        currentStatusDetail = getString(R.string.status_camera_streaming_detail)
        streamRunning = true
        updateStatus(getString(R.string.status_camera_streaming_title))
        addRecentEvent(getString(R.string.event_camera_stream_started))
    }

    /** Yalnizca masaustu camera_off komutu; telefon arayuzunde durdurma yok. */
    private fun stopCameraStreamFromPc() {
        stopService(Intent(this, CameraStreamService::class.java))
        streamRunning = false
        currentStatusDetail = ""
        updateStatus(getString(R.string.status_camera_stopped_from_desktop))
        addRecentEvent(getString(R.string.event_camera_stream_stopped_remote))
    }

    private fun stopAllStreams() {
        stopService(Intent(this, ScreenStreamService::class.java))
        stopService(Intent(this, CameraStreamService::class.java))
        streamRunning = false
        awaitingMediaProjectionConsent = false
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

        val profile = retryProfileFetch(token, deviceId)
        profile?.let { p ->
            sessionStore.saveProfile(p.firstName, p.lastName, p.email, p.phone)
        }

        val result = retryMeFetch(token, deviceId) ?: return
        val session = result
        if (session.address.isNotBlank()) {
            deviceId = session.address.filter(Char::isDigit).take(12)
            deviceIdentityStore.saveDeviceId(deviceId)
            sessionStore.save(session)
            currentAddress = session.address
            refreshFragments()
        }
    }

    private suspend fun retryProfileFetch(token: String, deviceId: String): UserProfile? {
        repeat(3) { attempt ->
            val result = backendApi.getProfile(token, deviceId)
            result.data?.let { return it }
            if (attempt < 2) delay(500L * (attempt + 1))
        }
        return null
    }

    private suspend fun retryMeFetch(token: String, deviceId: String): AuthSession? {
        repeat(3) { attempt ->
            val result = backendApi.getMe(token, deviceId)
            result.data?.let { return it }
            if (attempt < 2) delay(500L * (attempt + 1))
        }
        return null
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
                merged[key] = it.copy(
                    address = it.address?.filter(Char::isDigit)?.take(12),
                    paired = false,
                )
            }
        (recentResult.data ?: emptyList())
            .filter { it.deviceId != deviceId }
            .forEach { device ->
                val normalizedAddress = device.address?.filter(Char::isDigit)?.take(12)
                val key = normalizedAddress.orEmpty().ifBlank { device.deviceId }
                val existing = merged[key]
                merged[key] = if (existing == null) {
                    device.copy(address = normalizedAddress, paired = false)
                } else {
                    existing.copy(
                        username = existing.username ?: device.username,
                        deviceName = existing.deviceName ?: device.deviceName,
                        address = existing.address ?: normalizedAddress,
                        online = existing.online || device.online,
                        paired = existing.paired,
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
                    device.copy(address = normalizedAddress, paired = true)
                } else {
                    existing.copy(
                        username = existing.username ?: device.username,
                        deviceName = existing.deviceName ?: device.deviceName,
                        address = existing.address ?: normalizedAddress,
                        online = existing.online || device.online,
                        paired = true,
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
            .setTitle(getString(R.string.dialog_accessibility_required_title))
            .setMessage(getString(R.string.dialog_accessibility_required_message))
            .setPositiveButton(getString(R.string.dialog_open_settings)) { _, _ ->
                openAccessibilitySettingsScreen()
            }
            .setNegativeButton(getString(R.string.dialog_cancel), null)
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

    private fun createEventNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            EVENT_CHANNEL_ID,
            getString(R.string.settings_notifications_channel_name),
            NotificationManager.IMPORTANCE_DEFAULT,
        )
        manager.createNotificationChannel(channel)
    }

    private fun notifyConnectedIfEnabled() {
        if (!appSettingsStore.notifyOnConnect()) return
        postEventNotification(
            id = EVENT_NOTIFICATION_ID_CONNECTED,
            title = getString(R.string.settings_notify_connected_title),
            message = getString(R.string.settings_notify_connected_message),
        )
    }

    private fun notifyDisconnectedIfEnabled(message: String) {
        if (!appSettingsStore.notifyOnDisconnect()) return
        postEventNotification(
            id = EVENT_NOTIFICATION_ID_DISCONNECTED,
            title = getString(R.string.settings_notify_disconnected_title),
            message = message.ifBlank { getString(R.string.settings_notify_disconnected_message) },
        )
    }

    private fun postEventNotification(id: Int, title: String, message: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)?.apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = launchIntent?.let {
            PendingIntent.getActivity(
                this,
                id,
                it,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }

        val notification = NotificationCompat.Builder(this, EVENT_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(message)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .apply { if (pendingIntent != null) setContentIntent(pendingIntent) }
            .build()

        runCatching {
            NotificationManagerCompat.from(this).notify(id, notification)
        }
    }

    private fun updateStatus(message: String) {
        currentStatus = message
        refreshFragments()
    }

    private fun withControlReceiver(actionLabel: String, block: ControlReceiver.() -> Boolean) {
        val receiver = ControlReceiver.instance
        if (receiver == null) {
            currentStatus = getString(R.string.status_action_failed_template, actionLabel)
            currentStatusDetail = getString(R.string.status_action_failed_accessibility_detail)
            refreshFragments()
            openAccessibilitySettingsScreen()
            return
        }
        val success = receiver.block()
        if (!success) {
            currentStatus = getString(R.string.status_action_failed_template, actionLabel)
            currentStatusDetail = getString(R.string.status_action_failed_command_rejected_detail)
            refreshFragments()
        }
    }

    private fun updateAccessibilityHint() {
        accessibilityEnabled = isAccessibilityServiceEnabled()
        if (!accessibilityEnabled) {
            if (currentStatusDetail.isBlank() || currentStatusDetail.contains("erişilebilirlik", ignoreCase = true)) {
                currentStatusDetail = getString(R.string.status_accessibility_hint_detail)
            }
        }
    }

    suspend fun clearAllPairingsFromUi(): ClearPairingsResult {
        val token = sessionStore.authToken()
        if (token.isBlank()) return ClearPairingsResult(total = 0, cleared = 0, failed = 0)

        val targets = currentPairings
            .filter { it.paired && it.deviceId.isNotBlank() }
            .distinctBy { it.deviceId }

        if (targets.isEmpty()) return ClearPairingsResult(total = 0, cleared = 0, failed = 0)

        var cleared = 0
        var failed = 0
        targets.forEach { pairing ->
            val result = backendApi.deletePairing(token, deviceId, pairing.deviceId, pairing.address)
            if (result.error.isNullOrBlank()) {
                cleared += 1
            } else {
                failed += 1
            }
        }

        refreshPairings()
        if (cleared > 0) {
            addRecentEvent(getString(R.string.event_pairing_removed))
        }
        return ClearPairingsResult(total = targets.size, cleared = cleared, failed = failed)
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
        if (openingAccessibilitySettings) {
            openingAccessibilitySettings = false
        }
        if (sessionStore.isLoggedIn() && nowA11y && !hadA11y) {
            if (pairingAwaitingAccessibility) {
                Log.i(TAG, "Erişilebilirlik açıldı - mevcut oturum korunuyor")
                pairingAwaitingAccessibility = false
                remoteSessionPaired = false
                accessibilityEnabled = true
                currentStatus = getString(R.string.status_accessibility_enabled_title)
                currentStatusDetail = getString(R.string.status_accessibility_enabled_detail)
                addRecentEvent(getString(R.string.event_accessibility_enabled))
                refreshFragments()
                signalingClient?.pushAccessibilityToServer()
                Toast.makeText(this, getString(R.string.toast_accessibility_enabled), Toast.LENGTH_SHORT).show()
            } else {
                accessibilityEnabled = true
                signalingClient?.pushAccessibilityToServer()
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

    private fun addRecentEvent(message: String) {
        if (message.isBlank()) return
        if (recentEvents.firstOrNull()?.second == message) return
        recentEvents.addFirst(System.currentTimeMillis() to message)
        while (recentEvents.size > 12) {
            recentEvents.removeLast()
        }
    }
}

