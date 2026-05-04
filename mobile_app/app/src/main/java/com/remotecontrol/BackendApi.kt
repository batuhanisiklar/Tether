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
import java.util.concurrent.TimeUnit

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
    /** Yalnızca pairings endpoint'inden gelen (gerçek eşleşme) */
    val paired: Boolean = false,
) {
    fun displayName(): String = deviceName?.takeIf { it.isNotBlank() }
        ?: address
            ?.filter { it.isDigit() }
            ?.take(12)
            ?.chunked(4)
            ?.joinToString("-")
            ?.takeIf { it.isNotBlank() }
        ?: "...${deviceId.takeLast(8)}"
}

data class UserProfile(
    val userId: Int,
    val username: String,
    val email: String,
    val firstName: String,
    val lastName: String,
    val phone: String,
)

data class ProfileUpdateSession(
    val token: String,
    val userId: Int,
    val username: String,
)

class BackendApi(
    signalingUrl: String,
    private val client: OkHttpClient = Companion.defaultClient,
) {
    private companion object {
        /** Render cold start / yavas ag icin uzun zaman asimlari */
        val defaultClient: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(45, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(45, TimeUnit.SECONDS)
            .callTimeout(180, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }
    private val jsonType = "application/json; charset=utf-8".toMediaType()
    private val baseHttpUrl = signalingUrl
        .replaceFirst("wss://", "https://")
        .replaceFirst("ws://", "http://")
        .trimEnd('/')

    suspend fun login(
        email: String,
        password: String,
        deviceId: String,
        deviceType: String,
        deviceName: String,
        macAddress: String,
    ): ApiResult<AuthSession> {
        val em = email.trim().lowercase()
        val payload = JSONObject().apply {
            put("email", em)
            put("username", em)
            put("password", password)
            put("device_id", deviceId)
            put("device_type", deviceType)
            put("device_name", deviceName)
            if (macAddress.isNotBlank()) put("mac_address", macAddress)
        }
        return authRequest("/auth/login", payload)
    }

    suspend fun register(
        firstName: String,
        lastName: String,
        email: String,
        phone: String,
        password: String,
        deviceId: String,
        deviceType: String,
        deviceName: String,
        macAddress: String,
    ): ApiResult<AuthSession> {
        val em = email.trim().lowercase()
        val payload = JSONObject().apply {
            put("email", em)
            put("username", em)
            put("password", password)
            put("first_name", firstName.trim())
            put("last_name", lastName.trim())
            if (phone.isNotBlank()) put("phone", phone.trim())
            put("device_id", deviceId)
            put("device_type", deviceType)
            put("device_name", deviceName)
            if (macAddress.isNotBlank()) put("mac_address", macAddress)
        }
        return authRequest("/auth/register", payload)
    }

    suspend fun upsertDevice(
        token: String,
        deviceId: String,
        deviceType: String,
        deviceName: String,
        macAddress: String,
    ): ApiResult<String> = withContext(Dispatchers.IO) {
        try {
            val payload = JSONObject().apply {
                put("device_id", deviceId)
                put("device_type", deviceType)
                put("device_name", deviceName)
                if (macAddress.isNotBlank()) put("mac_address", macAddress)
            }
            val request = Request.Builder()
                .url("$baseHttpUrl/devices/upsert")
                .addHeader("Authorization", "Bearer $token")
                .post(payload.toString().toRequestBody(jsonType))
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return@withContext ApiResult(error = "Cihaz kaydi guncellenemedi.")
                }
                val address = runCatching { JSONObject(body).optString("address") }.getOrDefault("")
                ApiResult(data = address)
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

    suspend fun getDevices(token: String): ApiResult<List<DeviceSummary>> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseHttpUrl/devices")
                .addHeader("Authorization", "Bearer $token")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return@withContext ApiResult(error = "Cihaz listesi alinmadi.")
                }
                val json = JSONObject(body)
                val devices = parseDevices(json.optJSONArray("devices"))
                ApiResult(data = devices)
            }
        } catch (_: IOException) {
            ApiResult(error = "Cihaz listesi alinirken sunucuya ulasilamadi.")
        }
    }

    suspend fun getRecentDevices(token: String, deviceType: String): ApiResult<List<DeviceSummary>> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseHttpUrl/recent-devices?device_type=$deviceType")
                .addHeader("Authorization", "Bearer $token")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return@withContext ApiResult(error = "Recent cihaz listesi alinmadi.")
                }
                val json = JSONObject(body)
                val devices = parseDevices(json.optJSONArray("devices"))
                ApiResult(data = devices)
            }
        } catch (_: IOException) {
            ApiResult(error = "Recent cihaz listesi alinirken sunucuya ulasilamadi.")
        }
    }

    suspend fun deletePairing(
        token: String,
        deviceId: String,
        partnerDeviceId: String,
        partnerAddress: String?,
    ): ApiResult<Unit> = withContext(Dispatchers.IO) {
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

    suspend fun getMe(token: String, deviceId: String): ApiResult<AuthSession> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseHttpUrl/auth/me?device_id=$deviceId")
                .addHeader("Authorization", "Bearer $token")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return@withContext ApiResult(error = "Kullanici bilgisi alinamadi.")
                }
                return@withContext runCatching {
                    val json = JSONObject(body)
                    val user = json.getJSONObject("user")
                    val uid = when {
                        user.has("id") -> user.getInt("id")
                        user.has("user_id") -> user.getInt("user_id")
                        else -> -1
                    }
                    require(uid >= 0) { "missing user id" }
                    ApiResult(
                        data = AuthSession(
                            token = token,
                            userId = uid,
                            username = user.optString("username"),
                            address = user.optString("address"),
                        )
                    )
                }.getOrElse {
                    ApiResult(error = "Sunucu yaniti gecersiz (me parse basarisiz).")
                }
            }
        } catch (_: IOException) {
            ApiResult(error = "Kullanici bilgisi alinirken sunucuya ulasilamadi.")
        }
    }

    suspend fun getProfile(token: String, deviceId: String): ApiResult<UserProfile> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseHttpUrl/auth/me?device_id=$deviceId")
                .addHeader("Authorization", "Bearer $token")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return@withContext ApiResult(error = "Kullanici bilgisi alinamadi.")
                }
                return@withContext runCatching {
                    val json = JSONObject(body)
                    val user = json.getJSONObject("user")
                    val uid = when {
                        user.has("id") -> user.getInt("id")
                        user.has("user_id") -> user.getInt("user_id")
                        else -> -1
                    }
                    require(uid >= 0) { "missing user id" }
                    ApiResult(
                        data = UserProfile(
                            userId = uid,
                            username = user.optString("username").orEmpty(),
                            email = user.optString("email").orEmpty(),
                            firstName = user.optString("first_name").orEmpty(),
                            lastName = user.optString("last_name").orEmpty(),
                            phone = user.optString("phone").orEmpty(),
                        )
                    )
                }.getOrElse {
                    ApiResult(error = "Sunucu yaniti gecersiz (profile parse basarisiz).")
                }
            }
        } catch (_: IOException) {
            ApiResult(error = "Kullanici bilgisi alinirken sunucuya ulasilamadi.")
        }
    }

    suspend fun updateProfile(
        token: String,
        email: String,
        phone: String,
        oldPassword: String,
        password: String,
        password2: String,
    ): ApiResult<ProfileUpdateSession> = withContext(Dispatchers.IO) {
        try {
            val payload = JSONObject().apply {
                put("email", email.trim().lowercase())
                put("phone", phone.trim())
                if (password.isNotBlank() || password2.isNotBlank()) {
                    put("old_password", oldPassword)
                    put("password", password)
                    put("password2", password2)
                }
            }
            val request = Request.Builder()
                .url("$baseHttpUrl/auth/profile")
                .addHeader("Authorization", "Bearer $token")
                .post(payload.toString().toRequestBody(jsonType))
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val message = runCatching { JSONObject(body).optString("message") }.getOrDefault("")
                    return@withContext ApiResult(error = message.ifBlank { "Profil guncellenemedi." })
                }
                return@withContext runCatching {
                    val json = JSONObject(body)
                    val user = json.getJSONObject("user")
                    val newToken = json.optString("token").orEmpty()
                    val uid = when {
                        user.has("id") -> user.getInt("id")
                        user.has("user_id") -> user.getInt("user_id")
                        else -> -1
                    }
                    require(uid >= 0) { "missing user id" }
                    ApiResult(
                        data = ProfileUpdateSession(
                            token = newToken.ifBlank { token },
                            userId = uid,
                            username = user.optString("username").orEmpty(),
                        )
                    )
                }.getOrElse {
                    ApiResult(error = "Sunucu yaniti gecersiz (profile update parse basarisiz).")
                }
            }
        } catch (_: IOException) {
            ApiResult(error = "Profil guncellenirken sunucuya ulasilamadi.")
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
                // Sunucudan beklenmeyen JSON gelirse UYGULAMAYI cektirmesin diye korumalı parse.
                val parsed = runCatching {
                    val json = JSONObject(body)
                    val user = json.getJSONObject("user")
                    val authToken = json.getString("token")
                    val uid = when {
                        user.has("id") -> user.getInt("id")
                        user.has("user_id") -> user.getInt("user_id")
                        else -> -1
                    }
                    require(uid >= 0) { "missing user id" }
                    ApiResult(
                        data = AuthSession(
                            token = authToken,
                            userId = uid,
                            username = user.optString("username"),
                            address = user.optString("address"),
                        )
                    )
                }.getOrElse {
                    ApiResult(error = "Sunucu yaniti gecersiz (auth parse basarisiz).")
                }
                return@withContext parsed
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
                        paired = false,
                    )
                )
            }
        }
    }
}
