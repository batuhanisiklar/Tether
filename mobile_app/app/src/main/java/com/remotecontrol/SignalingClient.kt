package com.remotecontrol

import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Signaling sunucusuyla WebSocket üzerinden haberleşir.
 *
 * Birincil akış (otomatik bağlantı):
 *  - device_hello → sunucu bilinen eşleşmeyi kontrol eder
 *  - auto_paired → PC çevrimiçiyse direkt eşleşir
 *
 * İlk eşleşme (6 haneli kod):
 *  - register → PC join eder → paired → ikisi de pair_confirm gönderir
 */
class SignalingClient(
    private val serverUrl: String,
    private val deviceId: String,
    private val deviceAddress: String,
    private val preferredPartnerId: String? = null,
    private val preferredPartnerAddress: String? = null,
    private val allowAutoPair: Boolean = false,
    private val onPaired: (streamPort: Int, partnerDeviceId: String?) -> Unit,
    private val onPairedDevicesStatus: (pairedDeviceIds: List<String>, onlineDeviceIds: List<String>) -> Unit,
    private val onCommand: (action: String, params: Map<String, Any>) -> Unit,
    private val onDisconnected: () -> Unit,
) {
    companion object {
        private const val TAG = "SignalingClient"
        private const val MAX_PENDING_FRAME_BYTES = 1_500_000L
        fun generateCode(): String = (100_000..999_999).random().toString()

        /** Diğer servislerden frame göndermek için erişilebilir instance */
        var instance: SignalingClient? = null
    }

    val sessionCode: String = generateCode()

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private var ws: WebSocket? = null
    private var disconnectNotified = false
    private var manualClose = false

    fun connect() {
        instance = this
        disconnectNotified = false
        manualClose = false
        val request = Request.Builder().url(serverUrl).build()
        ws = client.newWebSocket(request, object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (webSocket != ws) return
                Log.i(TAG, "Connected to signaling server, device_id=$deviceId code=$sessionCode")

                // Önce device_hello gönder (persistent identity)
                val helloMsg = JSONObject().apply {
                    put("type", "device_hello")
                    put("device_id", deviceId)
                    put("role", "phone")
                    put("auto_pair", allowAutoPair)
                    if (allowAutoPair && !preferredPartnerId.isNullOrBlank()) {
                        put("preferred_partner_id", preferredPartnerId)
                    } else if (allowAutoPair && !preferredPartnerAddress.isNullOrBlank()) {
                        put("preferred_partner_id", preferredPartnerAddress)
                    }
                }
                webSocket.send(helloMsg.toString())

                // Kayıtlı bir PC hedeflenmiyorsa 6 haneli fallback kodu da aç.
                if (preferredPartnerId.isNullOrBlank() && preferredPartnerAddress.isNullOrBlank()) {
                    val registerMsg = JSONObject().apply {
                        put("type", "register")
                        put("code", sessionCode)
                        put("role", "phone")
                        put("device_id", deviceId)
                    }
                    webSocket.send(registerMsg.toString())
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (webSocket != ws) return
                Log.d(TAG, "Message: $text")
                try {
                    val json = JSONObject(text)
                    when (json.getString("type")) {
                        "registered" -> Log.i(TAG, "Registered with code=$sessionCode")

                        "device_ack" -> {
                            val pairedWith = json.optString("paired_with", "")
                            val partnerOnline = json.optBoolean("partner_online", false)
                            val pairedDevices = json.optJSONArray("paired_devices")
                                ?.let { array ->
                                    buildList {
                                        for (index in 0 until array.length()) {
                                            add(array.optString(index))
                                        }
                                    }
                                }
                                ?: emptyList()
                            val onlinePairedDevices = json.optJSONArray("online_paired_devices")
                                ?.let { array ->
                                    buildList {
                                        for (index in 0 until array.length()) {
                                            add(array.optString(index))
                                        }
                                    }
                                }
                                ?: emptyList()
                            Log.i(TAG, "Device ack: paired_with=$pairedWith online=$partnerOnline")
                            onPairedDevicesStatus(pairedDevices, onlinePairedDevices)
                        }

                        "auto_paired" -> {
                            val partnerDeviceId = json.optString("partner_device_id", "")
                            Log.i(TAG, "Auto-paired with PC: $partnerDeviceId")
                            scope.launch {
                                delay(500)
                                onPaired(8080, partnerDeviceId.ifBlank { null })
                            }
                        }

                        "paired" -> {
                            val partnerDeviceId = json.optString("partner_device_id", "")
                            Log.i(TAG, "Paired with PC via code!")
                            scope.launch {
                                delay(500)
                                onPaired(8080, partnerDeviceId.ifBlank { null })
                            }
                        }

                        "command" -> {
                            val action = json.optString("action", "")
                            val params = mutableMapOf<String, Any>()
                            json.keys().forEach { key ->
                                if (key != "type" && key != "action") {
                                    params[key] = json.get(key)
                                }
                            }
                            onCommand(action, params)
                        }

                        "peer_disconnected" -> {
                            Log.i(TAG, "PC disconnected")
                            notifyDisconnectedOnce()
                        }

                        "error" -> Log.e(TAG, "Server error: ${json.optString("message")}")
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Parse error: $e")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (webSocket != ws) return
                Log.e(TAG, "WS failure: $t")
                notifyDisconnectedOnce()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (webSocket != ws) return
                Log.i(TAG, "WS closed: $code $reason")
                notifyDisconnectedOnce()
            }
        })
    }

    /**
     * İlk kod ile eşleşme gerçekleşince çağrılır.
     * Sunucuya kalıcı pairing kaydedilir.
     */
    fun sendPairConfirm(pcDeviceId: String) {
        val msg = JSONObject().apply {
            put("type", "pair_confirm")
            put("my_device_id", deviceId)
            put("paired_with", pcDeviceId)
        }
        ws?.send(msg.toString())
        Log.i(TAG, "Sent pair_confirm: $deviceId <-> $pcDeviceId")
    }

    /**
     * Kamera/ekran JPEG frame'ini binary WebSocket paketi olarak relay eder.
     */
    fun sendFrame(jpeg: ByteArray) {
        val currentWs = ws
        if (currentWs == null) {
            Log.w(TAG, "WebSocket null - frame gönderilemedi")
            return
        }
        try {
            val queuedBytes = currentWs.queueSize()
            if (queuedBytes > MAX_PENDING_FRAME_BYTES) {
                if (Log.isLoggable(TAG, Log.DEBUG)) {
                    Log.d(TAG, "Frame atlandi: websocket kuyrugu dolu ($queuedBytes bytes)")
                }
                return
            }

            val sent = currentWs.send(jpeg.toByteString())
            if (!sent) {
                Log.w(TAG, "Frame gönderilemedi: websocket kabul etmedi")
                return
            }

            if (Log.isLoggable(TAG, Log.DEBUG)) {
                Log.d(TAG, "Binary frame gönderildi: ${jpeg.size} bytes")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Frame gönderme hatası: $e", e)
        }
    }

    fun notifyStreamReady(publicUrl: String) {
        val msg = JSONObject().apply {
            put("type", "stream_info")
            put("url", publicUrl)
        }
        ws?.send(msg.toString())
        Log.i(TAG, "Sent stream_info: $publicUrl")
    }

    fun disconnect(sendServerLogout: Boolean = false) {
        instance = null
        manualClose = true
        disconnectNotified = true
        val currentWs = ws
        ws = null
        if (sendServerLogout && currentWs != null) {
            try {
                val msg = JSONObject().apply {
                    put("type", "device_logout")
                    put("device_id", deviceId)
                }
                currentWs.send(msg.toString())
            } catch (_: Exception) {
            }
        }
        currentWs?.close(1000, "Client disconnect")
        scope.cancel()
        client.dispatcher.executorService.shutdown()
    }

    private fun notifyDisconnectedOnce() {
        if (manualClose) return
        if (disconnectNotified) return
        disconnectNotified = true
        onDisconnected()
    }
}
