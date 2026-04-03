package com.remotecontrol

import android.util.Base64
import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Signaling sunucusuyla WebSocket üzerinden haberleşir.
 *
 * Kalici kimlik + manuel oturum akisi:
 *  - device_hello: cihaz cevrimici ve presence takibi
 *  - register(code=deviceAddress): diger cihazlar bu adrese join olur
 *  - join(code=partnerAddress): manuel baglanti baslatir
 */
class SignalingClient(
    private val serverUrl: String,
    private val deviceId: String,
    private val deviceAddress: String,
    private val accessibilityEnabled: Boolean = true,
    private val onPaired: (streamPort: Int, partnerDeviceId: String?) -> Unit,
    private val onPairedDevicesStatus: (pairedDeviceIds: List<String>, onlineDeviceIds: List<String>) -> Unit,
    private val onCommand: (action: String, params: Map<String, Any>) -> Unit,
    private val onDisconnected: () -> Unit,
) {
    companion object {
        private const val TAG = "SignalingClient"
        private const val MAX_PENDING_FRAME_BYTES = 1_500_000L
        private const val PRESENCE_POLL_MS = 3_500L
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
    private var pendingJoinCode: String? = null

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
                    put("accessibility_enabled", accessibilityEnabled)
                }
                webSocket.send(helloMsg.toString())

                val registerCode = deviceAddress.filter(Char::isDigit).take(12).ifBlank { sessionCode }
                val registerMsg = JSONObject().apply {
                    put("type", "register")
                    put("code", registerCode)
                    put("role", "phone")
                    put("device_id", deviceId)
                    put("accessibility_enabled", accessibilityEnabled)
                }
                webSocket.send(registerMsg.toString())
                pendingJoinCode?.let { joinCode ->
                    val joinMsg = JSONObject().apply {
                        put("type", "join")
                        put("code", joinCode)
                        put("role", "phone")
                        put("device_id", deviceId)
                        put("accessibility_enabled", accessibilityEnabled)
                    }
                    webSocket.send(joinMsg.toString())
                    Log.i(TAG, "Sent deferred join for address=$joinCode")
                    pendingJoinCode = null
                }

                scope.launch {
                    while (isActive) {
                        delay(PRESENCE_POLL_MS)
                        val sock = ws ?: break
                        try {
                            sock.send(
                                JSONObject().apply { put("type", "request_presence") }.toString(),
                            )
                        } catch (_: Exception) {
                            break
                        }
                    }
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
                            fun jsonArrayToDeviceIds(array: JSONArray): List<String> = buildList {
                                for (index in 0 until array.length()) {
                                    val el = array.opt(index)
                                    val s = when (el) {
                                        is String -> el
                                        is Number -> el.toString()
                                        null -> ""
                                        else -> el.toString()
                                    }.filter { it.isDigit() }.take(12)
                                    if (s.length == 12) add(s)
                                }
                            }
                            val pairedDevices = json.optJSONArray("paired_devices")?.let(::jsonArrayToDeviceIds) ?: emptyList()
                            val onlinePairedDevices = json.optJSONArray("online_paired_devices")?.let(::jsonArrayToDeviceIds) ?: emptyList()
                            Log.i(TAG, "Device ack: paired_with=$pairedWith online=$partnerOnline")
                            onPairedDevicesStatus(pairedDevices, onlinePairedDevices)
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

    fun joinByAddress(rawAddress: String) {
        val joinCode = rawAddress.filter(Char::isDigit).take(12)
        if (joinCode.length != 12) return
        pendingJoinCode = joinCode
        val msg = JSONObject().apply {
            put("type", "join")
            put("code", joinCode)
            put("role", "phone")
            put("device_id", deviceId)
            put("accessibility_enabled", accessibilityEnabled)
        }
        val socket = ws
        if (socket != null) {
            socket.send(msg.toString())
            Log.i(TAG, "Sent join for address=$joinCode")
            pendingJoinCode = null
        } else {
            Log.i(TAG, "Join queued until websocket open: $joinCode")
        }
    }

    /**
     * JPEG karesini sunucuya JSON (base64) olarak gönderir; sunucu `frame` tipini eşe relay eder.
     *
     * Not: PaaS / ters vekil (Render vb.) WebSocket **binary** çerçevelerini düşürebiliyor;
     * metin çerçeveleri genelde sorunsuz iletilir.
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

            val b64 = Base64.encodeToString(jpeg, Base64.NO_WRAP)
            val msg = JSONObject().apply {
                put("type", "frame")
                put("data", b64)
            }
            val payload = msg.toString()
            val sent = currentWs.send(payload)
            if (!sent) {
                Log.w(TAG, "Frame gönderilemedi: websocket kabul etmedi")
                return
            }

            if (Log.isLoggable(TAG, Log.DEBUG)) {
                Log.d(TAG, "Frame JSON gönderildi: raw=${jpeg.size} bytes payload=${payload.length} chars")
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
