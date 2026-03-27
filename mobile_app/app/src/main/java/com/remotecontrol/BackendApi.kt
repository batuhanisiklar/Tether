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
    val address: String,
)

data class DeviceSummary(
    val deviceId: String,
    val deviceType: String,
    val deviceName: String?,
    val address: String?,
    val online: Boolean,
) {
    fun displayName(): String = deviceName?.takeIf { it.isNotBlank() }
        ?: address
            ?.filter { it.isDigit() }
            ?.take(12)
            ?.chunked(4)
            ?.joinToString(" ")
            ?.takeIf { it.isNotBlank() }
        ?: "...${deviceId.takeLast(8)}"
}

class BackendApi(
    signalingUrl: String,
    private val client: OkHttpClient = OkHttpClient(),
) {
    private val jsonType = "application/json; charset=utf-8".toMediaType()
    private val baseHttpUrl = signalingUrl
        .replaceFirst("wss://", "https://")
        .replaceFirst("ws://", "http://")
        .trimEnd('/')

    suspend fun login(
        username: String,
        password: String,
        deviceId: String,
        deviceType: String,
        deviceName: String,
    ): ApiResult<AuthSession> {
        val payload = JSONObject().apply {
            put("username", username)
            put("password", password)
            put("device_id", deviceId)
            put("device_type", deviceType)
            put("device_name", deviceName)
        }
        return authRequest("/auth/login", payload)
    }

    suspend fun register(
        username: String,
        password: String,
        deviceId: String,
        deviceType: String,
        deviceName: String,
    ): ApiResult<AuthSession> {
        val payload = JSONObject().apply {
            put("username", username)
            put("password", password)
            put("device_id", deviceId)
            put("device_type", deviceType)
            put("device_name", deviceName)
        }
        return authRequest("/auth/register", payload)
    }

    suspend fun upsertDevice(
        token: String,
        deviceId: String,
        deviceType: String,
        deviceName: String,
    ): ApiResult<Unit> = withContext(Dispatchers.IO) {
        try {
            val payload = JSONObject().apply {
                put("device_id", deviceId)
                put("device_type", deviceType)
                put("device_name", deviceName)
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

    suspend fun deletePairing(token: String, deviceId: String, partnerDeviceId: String): ApiResult<Unit> = withContext(Dispatchers.IO) {
        try {
            val payload = JSONObject().apply {
                put("device_id", deviceId)
                put("partner_device_id", partnerDeviceId)
            }
            val request = Request.Builder()
                .url("$baseHttpUrl/pairings/delete")
                .addHeader("Authorization", "Bearer $token")
                .post(payload.toString().toRequestBody(jsonType))
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val message = runCatching { JSONObject(body).optString("message") }.getOrDefault("")
                    return@withContext ApiResult(error = message.ifBlank { "Eslesme silinemedi." })
                }
                ApiResult(data = Unit)
            }
        } catch (_: IOException) {
            ApiResult(error = "Eslesme silinirken sunucuya ulasilamadi.")
        }
    }

    suspend fun getMe(token: String): ApiResult<AuthSession> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseHttpUrl/auth/me")
                .addHeader("Authorization", "Bearer $token")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return@withContext ApiResult(error = "Kullanici bilgisi alinamadi.")
                }
                val json = JSONObject(body)
                val user = json.getJSONObject("user")
                ApiResult(
                    data = AuthSession(
                        token = token,
                        userId = user.getInt("id"),
                        username = user.getString("username"),
                        address = user.optString("address"),
                    )
                )
            }
        } catch (_: IOException) {
            ApiResult(error = "Kullanici bilgisi alinirken sunucuya ulasilamadi.")
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
                        address = user.optString("address"),
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
                        deviceName = item.optString("device_name").takeIf { it.isNotBlank() },
                        address = item.optString("address").takeIf { it.isNotBlank() },
                        online = item.optBoolean("is_online", false),
                    )
                )
            }
        }
    }
}
