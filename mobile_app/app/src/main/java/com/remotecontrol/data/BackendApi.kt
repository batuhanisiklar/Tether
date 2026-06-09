package com.remotecontrol.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
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
    val statusCode: Int? = null,
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
    val username: String? = null,
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
                    return@withContext ApiResult(statusCode = response.code,
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Cihaz kaydı güncellenemedi.",
                        ),
                    )
                }
                val address = runCatching { JSONObject(body).optString("address") }.getOrDefault("")
                ApiResult(data = address)
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
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
                    return@withContext ApiResult(statusCode = response.code,
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Eşleşme listesi alınamadı.",
                        ),
                    )
                }
                val json = JSONObject(body)
                val pairings = parseDevices(json.optJSONArray("pairings"))
                ApiResult(data = pairings)
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
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
                    return@withContext ApiResult(
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Cihaz listesi alınamadı.",
                        ),
                    )
                }
                val json = JSONObject(body)
                val devices = parseDevices(json.optJSONArray("devices"))
                ApiResult(data = devices)
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
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
                    return@withContext ApiResult(
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Son kullanılan cihaz listesi alınamadı.",
                        ),
                    )
                }
                val json = JSONObject(body)
                val devices = parseDevices(json.optJSONArray("devices"))
                ApiResult(data = devices)
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
        }
    }

    @Suppress("UNUSED_PARAMETER")
    suspend fun deletePairing(
        token: String,
        deviceId: String,
        partnerDeviceId: String,
        _partnerAddress: String?,
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
                    return@withContext ApiResult(
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Eşleşme silinemedi.",
                        ),
                    )
                }
                ApiResult(data = Unit)
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
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
                    return@withContext ApiResult(statusCode = response.code,
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Kullanıcı bilgisi alınamadı.",
                        ),
                    )
                }
                return@withContext runCatching {
                    val json = JSONObject(body)
                    val user = json.getJSONObject("user")
                    // Sunucu yeni token donduruyorsa onu kullan (auto-refresh).
                    val refreshedToken = json.optString("token").orEmpty().ifBlank { token }
                    val uid = when {
                        user.has("id") -> user.getInt("id")
                        user.has("user_id") -> user.getInt("user_id")
                        else -> -1
                    }
                    require(uid >= 0) { "missing user id" }
                    ApiResult(
                        data = AuthSession(
                            token = refreshedToken,
                            userId = uid,
                            username = user.optString("username"),
                            address = user.optString("address"),
                        )
                    )
                }.getOrElse {
                    ApiResult(error = "Sunucu yanıtı işlenemedi. Lütfen tekrar deneyin.")
                }
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
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
                    return@withContext ApiResult(
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Profil bilgileri alınamadı.",
                        ),
                    )
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
                    ApiResult(error = "Sunucu yanıtı işlenemedi. Lütfen tekrar deneyin.")
                }
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
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
                    return@withContext ApiResult(
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Profil güncellenemedi.",
                        ),
                    )
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
                    ApiResult(error = "Sunucu yanıtı işlenemedi. Lütfen tekrar deneyin.")
                }
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
        }
    }

    suspend fun deleteAccount(
        token: String,
        email: String,
        password: String,
    ): ApiResult<Unit> = withContext(Dispatchers.IO) {
        try {
            val payload = JSONObject().apply {
                put("email", email.trim().lowercase())
                put("password", password)
            }
            val request = Request.Builder()
                .url("$baseHttpUrl/auth/delete")
                .addHeader("Authorization", "Bearer $token")
                .post(payload.toString().toRequestBody(jsonType))
                .build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return@withContext ApiResult(
                        error = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Hesap silinemedi.",
                        ),
                    )
                }
                ApiResult(data = Unit)
            }
        } catch (_: IOException) {
            ApiResult(error = BackendErrorMapper.mapNetworkError())
        }
    }

    private suspend fun authRequest(path: String, payload: JSONObject): ApiResult<AuthSession> = withContext(Dispatchers.IO) {
        for (attempt in 0 until 2) {
            try {
                val request = Request.Builder()
                    .url("$baseHttpUrl$path")
                    .post(payload.toString().toRequestBody(jsonType))
                    .build()

                var retryAfterUnauthorized = false
                var parsedResult: ApiResult<AuthSession>? = null

                client.newCall(request).execute().use { response ->
                    val body = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        val message = BackendErrorMapper.mapHttpError(
                            statusCode = response.code,
                            responseBody = body,
                            fallback = "Kimlik doğrulama başarısız.",
                        )
                        if (response.code == 401 && attempt == 0) {
                            retryAfterUnauthorized = true
                        } else {
                            parsedResult = ApiResult(error = message)
                        }
                        return@use
                    }
                    parsedResult = runCatching {
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
                        ApiResult(error = "Sunucu yanıtı işlenemedi. Lütfen tekrar deneyin.")
                    }
                }

                if (retryAfterUnauthorized) {
                    delay(1200)
                    continue
                }
                return@withContext parsedResult ?: ApiResult(error = "Kimlik doğrulama başarısız.")
            } catch (_: IOException) {
                if (attempt == 0) {
                    delay(1200)
                    continue
                }
                return@withContext ApiResult(error = BackendErrorMapper.mapNetworkError())
            }
        }
        ApiResult(error = "Giriş doğrulanamadı. Lütfen tekrar deneyin.")
    }
    private fun parseDevices(array: JSONArray?): List<DeviceSummary> {
        if (array == null) return emptyList()
        return buildList {
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                val owner = extractOwnerName(item)
                add(
                    DeviceSummary(
                        deviceId = item.optString("device_id"),
                        deviceType = item.optString("device_type"),
                        username = owner,
                        deviceName = item.optString("device_name").takeIf { it.isNotBlank() },
                        address = item.optString("address").takeIf { it.isNotBlank() },
                        online = item.optBoolean("is_online", false),
                        paired = false,
                    )
                )
            }
        }
    }

    private fun extractOwnerName(item: JSONObject): String? {
        val directFirst = firstNonBlank(
            item.optString("first_name"),
            item.optString("owner_first_name"),
            item.optString("user_first_name"),
        )
        val directLast = firstNonBlank(
            item.optString("last_name"),
            item.optString("owner_last_name"),
            item.optString("user_last_name"),
        )
        val fullFromDirect = listOf(directFirst, directLast).filter { it.isNotBlank() }.joinToString(" ")
        if (fullFromDirect.isNotBlank()) return fullFromDirect

        val ownerObj = item.optJSONObject("owner")
        if (ownerObj != null) {
            val ownerFirst = firstNonBlank(ownerObj.optString("first_name"), ownerObj.optString("firstName"))
            val ownerLast = firstNonBlank(ownerObj.optString("last_name"), ownerObj.optString("lastName"))
            val fullFromOwner = listOf(ownerFirst, ownerLast).filter { it.isNotBlank() }.joinToString(" ")
            if (fullFromOwner.isNotBlank()) return fullFromOwner
        }

        return firstNonBlank(
            item.optString("owner_name"),
            item.optString("username"),
            ownerObj?.optString("username").orEmpty(),
        ).ifBlank { null }
    }

    private fun firstNonBlank(vararg values: String): String {
        return values.firstOrNull { it.isNotBlank() }?.trim().orEmpty()
    }
}
