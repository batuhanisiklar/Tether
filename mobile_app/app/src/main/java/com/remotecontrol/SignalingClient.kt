package com.remotecontrol

import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import okio.ByteString.Companion.toByteString
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
    private val isAccessibilityEnabled: () -> Boolean,
    private val onPaired: (streamPort: Int, partnerDeviceId: String?) -> Unit,
    private val onPairedDevicesStatus: (pairedDeviceIds: List<String>, onlineDeviceIds: List<String>, partnerOnline: Boolean) -> Unit,
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

        /**
         * Tek OkHttpClient — her disconnect()'te dispatcher shutdown edilmez; yoksa yeniden baglantı
         * veya arka planda ScreenStreamService + yeni SignalingClient yarışında baglantı kopar / ws null olur.
         */
        private val sharedHttpClient by lazy {
            OkHttpClient.Builder()
                .pingInterval(25, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.MILLISECONDS)
                .writeTimeout(120, TimeUnit.SECONDS)
                .connectTimeout(30, TimeUnit.SECONDS)
                .retryOnConnectionFailure(true)
                .build()
        }
    }

    val sessionCode: String = generateCode()

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private var ws: WebSocket? = null
    private var disconnectNotified = false
    private var manualClose = false
    private var pendingJoinCode: String? = null
    private var lastNullWsLogMs: Long = 0L

    /** Cok buyuk JSON base64 cerceveleri proxy/WebSocket limitinde dusebilir; binary genelde sorunsuz. */
    private val maxJsonFrameBytes = 70_000

    /** Erisilebilirlik acildiktan sonra (ayarlardan donus vb.) sunucudaki bayragi gunceller. */
    fun pushAccessibilityToServer() {
        val socket = ws ?: return
        try {
            socket.send(
                JSONObject().apply {
                    put("type", "device_hello")
                    put("device_id", deviceId)
                    put("role", "phone")
                    put("accessibility_enabled", isAccessibilityEnabled())
                }.toString(),
            )
        } catch (_: Exception) {
        }
    }

    fun connect() {
        disconnectNotified = false
        manualClose = false
        instance = this
        val request = Request.Builder().url(serverUrl).build()
        ws = sharedHttpClient.newWebSocket(request, object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (webSocket != ws) return
                Log.i(TAG, "Connected to signaling server, device_id=$deviceId code=$sessionCode")

                // Önce device_hello gönder (persistent identity)
                val helloMsg = JSONObject().apply {
                    put("type", "device_hello")
                    put("device_id", deviceId)
                    put("role", "phone")
                    put("accessibility_enabled", isAccessibilityEnabled())
                }
                webSocket.send(helloMsg.toString())

                val registerCode = deviceAddress.filter(Char::isDigit).take(12).ifBlank { sessionCode }
                val registerMsg = JSONObject().apply {
                    put("type", "register")
                    put("code", registerCode)
                    put("role", "phone")
                    put("device_id", deviceId)
                    put("accessibility_enabled", isAccessibilityEnabled())
                }
                webSocket.send(registerMsg.toString())
                pendingJoinCode?.let { joinCode ->
                    val joinMsg = JSONObject().apply {
                        put("type", "join")
                        put("code", joinCode)
                        put("role", "phone")
                        put("device_id", deviceId)
                        put("accessibility_enabled", isAccessibilityEnabled())
                    }
                    webSocket.send(joinMsg.toString())
                    Log.i(TAG, "Sent deferred join for address=$joinCode")
                    pendingJoinCode = null
                }

                if (!scope.isActive) return

                scope.launch {
                    while (isActive) {
                        delay(PRESENCE_POLL_MS)
                        val sock = ws ?: break
                        try {
                            sock.send(
                                JSONObject().apply {
                                    put("type", "request_presence")
                                    put("accessibility_enabled", isAccessibilityEnabled())
                                }.toString(),
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
                            onPairedDevicesStatus(pairedDevices, onlinePairedDevices, partnerOnline)
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

                        "heartbeat", "joined", "waiting" -> { /* PC keep-alive / sunucu ack (yok say) */ }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Parse error: $e")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val ours = ws
                if (ours != null && webSocket != ours) return
                ws = null
                if (instance === this@SignalingClient) instance = null
                Log.e(TAG, "WS failure: $t")
                notifyDisconnectedOnce()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                val ours = ws
                if (ours != null && webSocket != ours) return
                ws = null
                if (instance === this@SignalingClient) instance = null
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
            put("accessibility_enabled", isAccessibilityEnabled())
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
     * JPEG'i binary WebSocket cercevesi olarak gonderir (sunucu `send_bytes` ile PC'ye iletir).
     * Kucuk karelerde istege bagli JSON fallback (cok nadir proxy senaryolari).
     */
    fun sendFrame(jpeg: ByteArray) {
        val currentWs = ws
        if (currentWs == null) {
            val now = System.currentTimeMillis()
            if (now - lastNullWsLogMs > 5_000L) {
                lastNullWsLogMs = now
                Log.w(TAG, "WebSocket yok — frame atlandi (signaling yeniden baglanincaya kadar)")
            }
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

            var sent = currentWs.send(jpeg.toByteString())
            if (!sent && jpeg.size <= maxJsonFrameBytes) {
                val b64 = android.util.Base64.encodeToString(jpeg, android.util.Base64.NO_WRAP)
                val msg = JSONObject().apply {
                    put("type", "frame")
                    put("data", b64)
                }
                sent = currentWs.send(msg.toString())
            }
            if (!sent) {
                Log.w(TAG, "Frame gonderilemedi (binary/fallback)")
                return
            }
            if (Log.isLoggable(TAG, Log.DEBUG)) {
                Log.d(TAG, "Frame gonderildi: ${jpeg.size} bytes (binary veya kucuk JSON)")
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
        if (instance === this) {
            instance = null
        }
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
        try {
            currentWs?.close(1000, "Client disconnect")
        } catch (_: Exception) {
        }
        scope.cancel()
    }

    private fun notifyDisconnectedOnce() {
        if (manualClose) return
        if (disconnectNotified) return
        disconnectNotified = true
        onDisconnected()
    }
}
