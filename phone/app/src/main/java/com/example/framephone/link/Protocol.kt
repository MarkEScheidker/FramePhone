package com.example.framephone.link

import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.security.MessageDigest

/** V1: bounded big-endian length-prefixed UTF-8 JSON over TLS 1.3. */
object Protocol {
    const val PORT = 47643
    const val VERSION = 1
    const val MAX_MESSAGE = 65536
    const val DISCOVERY = "FRAMEPHONE_DISCOVER_V1"
    fun hash(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it.toInt() and 255) }
    fun fingerprint(hash: String): String = hash.take(16).uppercase().chunked(4).joinToString(" ")
    fun pairingFingerprint(pin: String, clientNonce: String, phoneNonce: String): String {
        require(listOf(pin, clientNonce, phoneNonce).all { it.matches(Regex("[0-9a-f]{64}")) })
        return fingerprint(hash((pin + clientNonce + phoneNonce).toByteArray(Charsets.US_ASCII)))
    }
    fun read(input: DataInputStream): JSONObject {
        val size = input.readInt()
        require(size in 1..MAX_MESSAGE) { "Invalid message size" }
        val bytes = ByteArray(size)
        input.readFully(bytes)
        // Bound nesting before invoking Android's recursive JSON parser.
        var depth = 0
        var quoted = false
        var escaped = false
        bytes.forEach { byte ->
            val c = byte.toInt().toChar()
            if (quoted) {
                if (escaped) escaped = false
                else if (c == '\\') escaped = true
                else if (c == '"') quoted = false
            } else when (c) {
                '"' -> quoted = true
                '{', '[' -> { depth++; require(depth <= 8) { "Message nesting too deep" } }
                '}', ']' -> { depth--; require(depth >= 0) }
            }
        }
        require(depth == 0 && !quoted)
        return JSONObject(bytes.toString(Charsets.UTF_8))
    }
    fun write(output: DataOutputStream, message: JSONObject) {
        val bytes = message.toString().toByteArray(Charsets.UTF_8)
        require(bytes.size in 1..MAX_MESSAGE)
        synchronized(output) {
            output.writeInt(bytes.size)
            output.write(bytes)
            output.flush()
        }
    }
}

data class PhoneDimensions(val widthMm: Double, val heightMm: Double, val thicknessMm: Double) {
    init {
        require(widthMm.isFinite() && widthMm in 20.0..500.0)
        require(heightMm.isFinite() && heightMm in widthMm..800.0)
        require(thicknessMm.isFinite() && thicknessMm in 1.0..100.0)
    }
    fun json() = JSONObject().put("width_m", widthMm / 1000)
        .put("height_m", heightMm / 1000).put("thickness_m", thicknessMm / 1000)
        .put("boundary", "body_or_case").put("source", "manual")
}
