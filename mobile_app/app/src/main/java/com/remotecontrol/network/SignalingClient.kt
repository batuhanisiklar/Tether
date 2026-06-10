package com.remotecontrol.network

import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import okio.ByteString.Companion.toByteString
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class PartnerIdentity(
    val deviceId: String,
    val address: String,
    val deviceName: String,
    val deviceType: String,
    val ownerName: String,
    val ownerEmail: String,
) {
    fun deviceNumber(): String {
        val digits = address.ifBlank { deviceId }.filter(Char::isDigit).take(12)
        return digits.chunked(4).joinToString("-").ifBlank { "Bilinmiyor" }
    }

    fun displayName(): String {
        val owner = ownerName.takeIf { it.isNotBlank() } ?: ownerEmail.takeIf { it.isNotBlank() }
        return listOfNotNull(owner, deviceName.takeIf { it.isNotBlank() })
            .distinct()
            .joinToString(" - ")
            .takeIf { it.isNotBlank() }
            ?: deviceId.takeLast(4).takeIf { it.isNotBlank() }?.let { "Bilgisayar ...$it" }
            ?: "Bilgisayar"
    }
}








class SignalingClient(
    private val serverUrl: String,
    private val authToken: String,
    private val deviceId: String,
    private val deviceAddress: String,
    private val isAccessibilityEnabled: () -> Boolean,
    private val isMediaMuted: () -> Boolean?,
    private val onPairRequest: (partner: PartnerIdentity?) -> Unit,
    private val onPaired: (streamPort: Int, partner: PartnerIdentity?) -> Unit,
    private val onPairedDevicesStatus: (pairedDeviceIds: List<String>, onlineDeviceIds: List<String>, partnerOnline: Boolean) -> Unit,
    private val onCommand: (action: String, params: Map<String, Any>) -> Unit,
    
    private val onPeerSessionEnded: () -> Unit,
    
    private val onTransportDisconnected: () -> Unit,
) {
    companion object {
        private const val TAG = "SignalingClient"
        private const val MAX_PENDING_FRAME_BYTES = 2_600_000L
        private const val PRESENCE_POLL_MS = 3_500L
        
        var instance: SignalingClient? = null

        



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

    val sessionCode: String = deviceId.filter(Char::isDigit).take(12)

    private var scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private var ws: WebSocket? = null
    private var disconnectNotified = false
    private var manualClose = false
    private var lastNullWsLogMs: Long = 0L
    private var consecutiveDrops: Int = 0
    private val maxJsonFrameBytes = 70_000

    private fun partnerIdentityFrom(json: JSONObject): PartnerIdentity? {
        val partnerDeviceId = json.optString("partner_device_id", "")
        return PartnerIdentity(
            deviceId = partnerDeviceId.filter(Char::isDigit).take(12),
            address = json.optString("partner_address", "").filter(Char::isDigit).take(12),
            deviceName = json.optString("partner_device_name", "").trim(),
            deviceType = json.optString("partner_device_type", "").trim(),
            ownerName = json.optString("partner_owner_name", "").trim(),
            ownerEmail = json.optString("partner_owner_email", "").trim(),
        ).takeIf {
            it.deviceId.isNotBlank() ||
                it.deviceName.isNotBlank() ||
                it.ownerName.isNotBlank() ||
                it.ownerEmail.isNotBlank()
        }
    }

    
    fun pushAccessibilityToServer() {
        val socket = ws ?: return
        try {
            socket.send(
                JSONObject().apply {
                    put("type", "device_hello")
                    put("auth_token", authToken)
                    put("device_id", deviceId)
                    put("role", "phone")
                    put("accessibility_enabled", isAccessibilityEnabled())
                    isMediaMuted()?.let { put("media_muted", it) }
                }.toString(),
            )
        } catch (_: Exception) {
        }
    }

    
    fun pushPresenceSnapshotToServer() {
        val socket = ws ?: return
        sendPresenceSnapshot(socket)
    }

    private fun sendPresenceSnapshot(socket: WebSocket): Boolean {
        return try {
            socket.send(
                JSONObject().apply {
                    put("type", "request_presence")
                    put("auth_token", authToken)
                    put("accessibility_enabled", isAccessibilityEnabled())
                    isMediaMuted()?.let { muted -> put("media_muted", muted) }
                }.toString(),
            )
        } catch (_: Exception) {
            false
        }
    }

    
    fun sendAccessibilityError() {
        val socket = ws ?: return
        try {
            socket.send(
                JSONObject().apply {
                    put("type", "command")
                    put("action", "accessibility_error")
                    put("code", "accessibility_required")
                    put("message", "Telefonda Erisilebilirlik servisi kapali. Ayarlardan acin ve tekrar deneyin.")
                }.toString(),
            )
        } catch (_: Exception) {
        }
    }

    fun connect() {
        disconnectNotified = false
        manualClose = false
        instance = this
        
        if (!scope.isActive) {
            scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        }
        val request = Request.Builder().url(serverUrl).build()
        ws = sharedHttpClient.newWebSocket(request, object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (webSocket != ws) return
                Log.i(TAG, "Connected to signaling server, device_id=$deviceId code=$sessionCode")

                
                val helloMsg = JSONObject().apply {
                    put("type", "device_hello")
                    put("auth_token", authToken)
                    put("device_id", deviceId)
                    put("role", "phone")
                    put("accessibility_enabled", isAccessibilityEnabled())
                    isMediaMuted()?.let { put("media_muted", it) }
                }
                webSocket.send(helloMsg.toString())

                val registerCode = deviceAddress.filter(Char::isDigit).take(12).ifBlank { sessionCode }
                if (registerCode.length != 12) {
                    Log.e(TAG, "12 haneli device address yok; signaling register iptal edildi")
                    webSocket.close(1008, "device address required")
                    return
                }
                Log.i(TAG, "Registering with code=$registerCode (deviceAddress-based)")
                val registerMsg = JSONObject().apply {
                    put("type", "register")
                    put("auth_token", authToken)
                    put("code", registerCode)
                    put("role", "phone")
                    put("device_id", deviceId)
                    put("accessibility_enabled", isAccessibilityEnabled())
                    isMediaMuted()?.let { put("media_muted", it) }
                }
                webSocket.send(registerMsg.toString())

                if (!scope.isActive) return

                scope.launch {
                    while (isActive) {
                        delay(PRESENCE_POLL_MS)
                        val sock = ws ?: break
                        if (!sendPresenceSnapshot(sock)) {
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
                        "registered" -> {
                            val regCode = json.optString("code", sessionCode)
                            Log.i(TAG, "Registered with code=$regCode")
                        }

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

                        "pair_request" -> {
                            val partner = partnerIdentityFrom(json)
                            Log.i(TAG, "Pair request received")
                            onPairRequest(partner)
                        }

                        "paired" -> {
                            val partner = partnerIdentityFrom(json)
                            Log.i(TAG, "Paired with PC via code!")
                            scope.launch {
                                delay(500)
                                onPaired(8080, partner)
                            }
                        }

                        "session_ping" -> {
                            val pid = json.optInt("ping_id", 0)
                            try {
                                webSocket.send(
                                    JSONObject().apply {
                                        put("type", "session_pong")
                                        put("ping_id", pid)
                                    }.toString(),
                                )
                            } catch (_: Exception) {
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
                            Log.i(TAG, "PC oturumu kapandi (signaling acik)")
                            onPeerSessionEnded()
                        }

                        "error" -> Log.e(TAG, "Server error: ${json.optString("message")}")

                        "heartbeat", "joined", "waiting" -> {  }
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
                notifyTransportDisconnectedOnce()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                val ours = ws
                if (ours != null && webSocket != ours) return
                ws = null
                if (instance === this@SignalingClient) instance = null
                Log.i(TAG, "WS closed: $code $reason")
                notifyTransportDisconnectedOnce()
            }
        })
    }

    



    fun sendPairConfirm(pcDeviceId: String) {
        val msg = JSONObject().apply {
            put("type", "pair_confirm")
            put("auth_token", authToken)
            put("my_device_id", deviceId)
            put("paired_with", pcDeviceId)
        }
        ws?.send(msg.toString())
        Log.i(TAG, "Sent pair_confirm: $deviceId <-> $pcDeviceId")
    }

    fun sendPairReject(pcDeviceId: String) {
        val msg = JSONObject().apply {
            put("type", "pair_reject")
            put("auth_token", authToken)
            put("my_device_id", deviceId)
            put("rejected_device_id", pcDeviceId)
        }
        ws?.send(msg.toString())
        Log.i(TAG, "Sent pair_reject: $deviceId x $pcDeviceId")
    }

    
    fun pendingQueueBytes(): Long = ws?.queueSize() ?: 0L

    








    fun sendFrame(jpeg: ByteArray, rotation: Int = 0) {
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
                consecutiveDrops++
                if (consecutiveDrops == 1 || consecutiveDrops % 50 == 0) {
                    Log.w(TAG, "Frame atlandi: websocket kuyrugu dolu ($queuedBytes bytes, art arda $consecutiveDrops drop)")
                }
                return
            }
            consecutiveDrops = 0

            
            val rotByte: Byte = when (rotation) {
                android.view.Surface.ROTATION_0   -> 0x00
                android.view.Surface.ROTATION_90  -> 0x01
                android.view.Surface.ROTATION_180 -> 0x02
                android.view.Surface.ROTATION_270 -> 0x03
                else -> 0x00
            }

            val payload = ByteArray(jpeg.size + 2)
            payload[0] = 0x01          
            payload[1] = rotByte       
            System.arraycopy(jpeg, 0, payload, 2, jpeg.size)

            var sent = currentWs.send(payload.toByteString())
            if (!sent && jpeg.size <= maxJsonFrameBytes) {
                val b64 = android.util.Base64.encodeToString(jpeg, android.util.Base64.NO_WRAP)
                val msg = JSONObject().apply {
                    put("type", "frame")
                    put("data", b64)
                    put("rotation", rotation)
                }
                sent = currentWs.send(msg.toString())
            }
            if (!sent) {
                Log.w(TAG, "Frame gonderilemedi (binary/fallback)")
                return
            }
            if (Log.isLoggable(TAG, Log.DEBUG)) {
                Log.d(TAG, "Frame gonderildi: ${jpeg.size} bytes rot=$rotation")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Frame gönderme hatası: $e", e)
        }
    }

    



    fun sendAudio(pcm: ByteArray) {
        val currentWs = ws ?: return
        try {
            val queuedBytes = currentWs.queueSize()
            if (queuedBytes > MAX_PENDING_FRAME_BYTES) {
                return
            }
            val payload = ByteArray(pcm.size + 1)
            payload[0] = 0x02
            System.arraycopy(pcm, 0, payload, 1, pcm.size)
            currentWs.send(payload.toByteString())
        } catch (e: Exception) {
            Log.e(TAG, "Ses gönderme hatası: $e")
        }
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
                    put("auth_token", authToken)
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

    private fun notifyTransportDisconnectedOnce() {
        if (manualClose) return
        if (disconnectNotified) return
        disconnectNotified = true
        onTransportDisconnected()
    }
}
