package com.remotecontrol.data

import org.json.JSONObject
import java.util.Locale

/**
 * Sunucudan gelen hata kodu/mesajini kullaniciya gosterilecek
 * tutarli ve anlasilir Turkce metne cevirir.
 */
object BackendErrorMapper {

    fun mapHttpError(statusCode: Int, responseBody: String?, fallback: String): String {
        val code = extractCode(responseBody)
        val serverMessage = extractMessage(responseBody)

        return when {
            code != null -> mapCode(code)
            statusCode == 401 -> "Oturum doğrulanamadı. E-posta ve şifrenizi kontrol edin."
            statusCode == 403 -> "Bu işlem için yetkiniz bulunmuyor."
            statusCode == 404 -> "İlgili kayıt bulunamadı."
            statusCode == 409 -> "Bu işlem mevcut verilerle çakışıyor."
            statusCode == 422 -> "Gönderilen bilgiler geçersiz. Alanları kontrol edip tekrar deneyin."
            statusCode == 429 -> "Çok fazla istek gönderildi. Lütfen kısa bir süre sonra tekrar deneyin."
            statusCode in 500..599 -> "Sunucu tarafında geçici bir sorun oluştu. Lütfen daha sonra tekrar deneyin."
            !serverMessage.isNullOrBlank() -> sanitizeServerMessage(serverMessage)
            else -> fallback
        }
    }

    fun mapNetworkError(): String {
        return "Sunucuya ulaşılamadı. İnternet bağlantınızı ve sunucu adresini kontrol edin."
    }

    private fun extractCode(responseBody: String?): String? {
        if (responseBody.isNullOrBlank()) return null
        val json = runCatching { JSONObject(responseBody) }.getOrNull() ?: return null
        val rawCode = when {
            json.has("code") -> json.opt("code")
            json.has("error_code") -> json.opt("error_code")
            json.has("error") -> json.opt("error")
            else -> null
        } ?: return null
        return rawCode.toString().trim().lowercase(Locale.ROOT).ifBlank { null }
    }

    private fun extractMessage(responseBody: String?): String? {
        if (responseBody.isNullOrBlank()) return null
        val json = runCatching { JSONObject(responseBody) }.getOrNull() ?: return null
        return listOf("message", "detail", "error_description")
            .firstNotNullOfOrNull { key -> json.optString(key).takeIf { it.isNotBlank() } }
    }

    private fun mapCode(code: String): String {
        return when (code) {
            "invalid_credentials", "wrong_password", "auth_failed" ->
                "Giriş bilgileri hatalı. E-posta ve şifrenizi kontrol edin."
            "unauthorized", "token_invalid", "token_expired", "invalid_token" ->
                "Oturum süreniz dolmuş olabilir. Lütfen yeniden giriş yapın."
            "forbidden", "permission_denied" ->
                "Bu işlem için yetkiniz bulunmuyor."
            "user_not_found" ->
                "Kullanıcı bulunamadı."
            "device_not_found" ->
                "Cihaz kaydı bulunamadı."
            "pairing_not_found" ->
                "Eşleşme kaydı bulunamadı."
            "pairing_exists", "already_paired" ->
                "Bu cihaz zaten eşleşmiş görünüyor."
            "email_already_exists", "duplicate_email", "username_taken" ->
                "Bu e-posta adresi zaten kullanımda."
            "validation_error", "invalid_request", "bad_request", "missing_fields" ->
                "Gönderilen bilgiler geçersiz. Alanları kontrol edip tekrar deneyin."
            "invalid_email" ->
                "E-posta adresi geçersiz görünüyor."
            "weak_password", "password_too_short" ->
                "Şifre güvenlik koşullarını sağlamıyor. Daha güçlü bir şifre deneyin."
            "password_mismatch" ->
                "Girilen şifreler birbiriyle uyuşmuyor."
            "rate_limited", "too_many_requests" ->
                "Çok fazla deneme yapıldı. Lütfen kısa bir süre sonra tekrar deneyin."
            "server_error", "internal_error", "service_unavailable" ->
                "Sunucu tarafında geçici bir sorun oluştu. Lütfen daha sonra tekrar deneyin."
            else ->
                "İşlem tamamlanamadı. Lütfen tekrar deneyin."
        }
    }

    private fun sanitizeServerMessage(message: String): String {
        // Sunucudan dönen çok teknik veya boşluklu mesajları sadeleştir.
        val clean = message.trim().replace(Regex("\\s+"), " ")
        if (clean.length > 220) {
            return "İşlem tamamlanamadı. Lütfen tekrar deneyin."
        }
        return clean
    }
}
