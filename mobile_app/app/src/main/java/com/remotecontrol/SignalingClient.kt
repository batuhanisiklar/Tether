package com.remotecontrol

import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import okio.ByteString
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
    private val onPaired: (streamPort: Int, partnerDeviceId: String?) -> Unit,
    private val onCommand: (action: String, params: Map<String, Any>) -> Unit,
    private val onDisconnected: () -> Unit,
) {
    companion object {
        private const val TAG = "SignalingClient"
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

    fun connect() {
        instance = this
        val request = Request.Builder().url(serverUrl).build()
        ws = client.newWebSocket(request, object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "Connected to signaling server, device_id=$deviceId code=$sessionCode")

                // Önce device_hello gönder (persistent identity)
                val helloMsg = JSONObject().apply {
                    put("type", "device_hello")
                    put("device_id", deviceId)
                    put("role", "phone")
                }
                webSocket.send(helloMsg.toString())

                // Ayrıca 6-haneli kod ile de kayıt ol (ilk eşleşme için fallback)
                val registerMsg = JSONObject().apply {
                    put("type", "register")
                    put("code", sessionCode)
                    put("role", "phone")
                    put("device_id", deviceId)
                }
                webSocket.send(registerMsg.toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "Message: $text")
                try {
                    val json = JSONObject(text)
                    when (json.getString("type")) {
                        "registered" -> Log.i(TAG, "Registered with code=$sessionCode")

                        "device_ack" -> {
                            val pairedWith = json.optString("paired_with", "")
                            val partnerOnline = json.optBoolean("partner_online", false)
                            Log.i(TAG, "Device ack: paired_with=$pairedWith online=$partnerOnline")
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
                            onDisconnected()
                        }

                        "error" -> Log.e(TAG, "Server error: ${json.optString("message")}")
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Parse error: $e")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WS failure: $t")
                onDisconnected()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WS closed: $code $reason")
                onDisconnected()
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
     * Kamera/ekran JPEG frame'ini Base64 JSON olarak PC'ye relay eder.
     */
    fun sendFrame(jpeg: ByteArray) {
        val currentWs = ws
        if (currentWs == null) {
            Log.w(TAG, "WebSocket null - frame gönderilemedi")
            return
        }
        try {
            val b64 = android.util.Base64.encodeToString(jpeg, android.util.Base64.NO_WRAP)
            val msg = JSONObject().apply {
                put("type", "frame")
                put("data", b64)
            }
            currentWs.send(msg.toString())
            if (Log.isLoggable(TAG, Log.DEBUG)) {
                Log.d(TAG, "Frame gönderildi: ${jpeg.size} bytes -> ${b64.length} chars base64")
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

    fun disconnect() {
        ws?.close(1000, "Client disconnect")
        scope.cancel()
        client.dispatcher.executorService.shutdown()
    }
}
