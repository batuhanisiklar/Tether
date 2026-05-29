package com.remotecontrol.util

object AddressUtils {
    fun digits(value: String?): String = value.orEmpty().filter(Char::isDigit).take(12)

    fun isValid(value: String?): Boolean = digits(value).length == 12

    fun format(value: String?): String {
        val digits = digits(value)
        return if (digits.isEmpty()) "----" + "-" + "----" + "-" + "----" else digits.chunked(4).joinToString("-")
    }
}
