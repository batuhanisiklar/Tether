package com.remotecontrol

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException

data class ApiResult<T>(
    val data: T? = null,
    val error: String? = null,
)

data class AuthSession(
    val token: String,
    val userId: Int,
    val username: String,
)

data class DeviceSummary(
    val deviceId: String,
    val deviceType: String,
    val lastSeen: String?,
    val online: Boolean,
)

class BackendApi(
    signalingUrl: String,
    private val client: OkHttpClient = OkHttpClient(),
) {
    private val jsonType = "application/json; charset=utf-8".toMediaType()
    private val baseHttpUrl = signalingUrl
        .replaceFirst("wss://", "https://")
        .replaceFirst("ws://", "http://")
        .trimEnd('/')

    suspend fun login(username: String, password: String, deviceId: String, deviceType: String): ApiResult<AuthSession> {
        val payload = JSONObject().apply {
            put("username", username)
            put("password", password)
            put("device_id", deviceId)
            put("device_type", deviceType)
        }
        return authRequest("/auth/login", payload)
    }

    suspend fun register(username: String, password: String, deviceId: String, deviceType: String): ApiResult<AuthSession> {
        val payload = JSONObject().apply {
            put("username", username)
            put("password", password)
            put("device_id", deviceId)
            put("device_type", deviceType)
        }
        return authRequest("/auth/register", payload)
    }

    suspend fun upsertDevice(token: String, deviceId: String, deviceType: String): ApiResult<Unit> = withContext(Dispatchers.IO) {
        try {
            val payload = JSONObject().apply {
                put("device_id", deviceId)
                put("device_type", deviceType)
            }
            val request = Request.Builder()
                .url("$baseHttpUrl/devices/upsert")
                .addHeader("Authorization", "Bearer $token")
                .post(payload.toString().toRequestBody(jsonType))
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    return@withContext ApiResult(error = "Cihaz kaydi guncellenemedi.")
                }
                ApiResult(data = Unit)
            }
        } catch (_: IOException) {
            ApiResult(error = "Sunucuya ulasilamadi. Baglanti adresini kontrol edin.")
        }
    }

    suspend fun getPairings(token: String, deviceId: String): ApiResult<List<DeviceSummary>> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseHttpUrl/pairings?device_id=$deviceId")
                .addHeader("Authorization", "Bearer $token")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return@withContext ApiResult(error = "Cihaz listesi alinmadi.")
                }
                val json = JSONObject(body)
                val pairings = parseDevices(json.optJSONArray("pairings"))
                ApiResult(data = pairings)
            }
        } catch (_: IOException) {
            ApiResult(error = "Cihaz listesi alinirken sunucuya ulasilamadi.")
        }
    }

    private suspend fun authRequest(path: String, payload: JSONObject): ApiResult<AuthSession> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseHttpUrl$path")
                .post(payload.toString().toRequestBody(jsonType))
                .build()

            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val message = when (response.code) {
                        404, 405 -> "Sunucuda kimlik dogrulama API'si aktif degil. Guncel sunucuyu calistirin."
                        401 -> runCatching { JSONObject(body).optString("message") }.getOrDefault("Kullanici adi veya sifre hatali.")
                        else -> runCatching { JSONObject(body).optString("message") }.getOrDefault("").ifBlank {
                            "Kimlik dogrulama basarisiz."
                        }
                    }
                    return@withContext ApiResult(error = message)
                }

                val json = JSONObject(body)
                val user = json.getJSONObject("user")
                ApiResult(
                    data = AuthSession(
                        token = json.getString("token"),
                        userId = user.getInt("id"),
                        username = user.getString("username"),
                    )
                )
            }
        } catch (_: IOException) {
            ApiResult(error = "Sunucuya ulasilamadi. URL ve internet baglantisini kontrol edin.")
        }
    }

    private fun parseDevices(array: JSONArray?): List<DeviceSummary> {
        if (array == null) return emptyList()
        return buildList {
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                add(
                    DeviceSummary(
                        deviceId = item.optString("device_id"),
                        deviceType = item.optString("device_type"),
                        lastSeen = item.optString("last_seen").takeIf { it.isNotBlank() },
                        online = item.optBoolean("online", false),
                    )
                )
            }
        }
    }
}
