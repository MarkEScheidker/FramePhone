package com.example.framephone.bluetooth

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLEngineResult

/** TLS 1.3 over ordered bytes. Bluetooth owns transport, not encryption keys. */
internal class BluetoothTls(context: SSLContext) {
    private val engine = context.createSSLEngine().apply {
        useClientMode = false
        enabledProtocols = arrayOf("TLSv1.3")
        needClientAuth = false
        beginHandshake()
    }
    private val input = ByteBuffer.allocate(65536)
    private val output = ByteArrayOutputStream()
    private val decoded = ByteBuffer.allocate(65536)
    private val encoded = ByteBuffer.allocate(65536)
    private var plain = byteArrayOf()
    val ready: Boolean get() = engine.handshakeStatus == SSLEngineResult.HandshakeStatus.NOT_HANDSHAKING

    fun receive(bytes: ByteArray): List<ByteArray> {
        require(bytes.size <= input.remaining())
        input.put(bytes).flip()
        var steps = 0
        while (steps++ < 100) {
            when (engine.handshakeStatus) {
                SSLEngineResult.HandshakeStatus.NEED_TASK -> {
                    val task = engine.delegatedTask ?: error("TLS task unavailable")
                    task.run()
                }
                SSLEngineResult.HandshakeStatus.NEED_WRAP -> wrap(ByteBuffer.allocate(0))
                else -> {
                    if (!input.hasRemaining()) break
                    val target = decoded.apply { clear() }
                    val result = engine.unwrap(input, target)
                    check(result.status != SSLEngineResult.Status.CLOSED) { "Bluetooth TLS closed" }
                    check(result.status != SSLEngineResult.Status.BUFFER_OVERFLOW)
                    if (target.position() > 0) plain += target.array().copyOf(target.position())
                    if (result.status == SSLEngineResult.Status.BUFFER_UNDERFLOW) {
                        break
                    }
                }
            }
        }
        input.compact()
        return messages()
    }

    private fun messages(): List<ByteArray> {
        require(plain.size <= 65540)
        val result = mutableListOf<ByteArray>()
        while (plain.size >= 4) {
            val size = ByteBuffer.wrap(plain, 0, 4).int
            require(size in 1..65536)
            if (plain.size < size+4) break
            result += plain.copyOfRange(4, size+4)
            plain = plain.copyOfRange(size+4, plain.size)
        }
        return result
    }

    private fun wrap(source: ByteBuffer) {
        val target = encoded.apply { clear() }
        val result = engine.wrap(source, target)
        check(result.status == SSLEngineResult.Status.OK) { "Bluetooth TLS write failed" }
        output.write(target.array(), 0, target.position())
    }

    fun send(payload: ByteArray) {
        check(ready)
        require(payload.size in 1..65536)
        val source = ByteBuffer.allocate(payload.size+4).apply { putInt(payload.size); put(payload); flip() }
        while (source.hasRemaining()) wrap(source)
    }

    fun take(): ByteArray = output.toByteArray().also { output.reset() }

    companion object {
        fun code(pin: String, headsetNonce: String, phoneNonce: String): String {
            require(listOf(pin, headsetNonce, phoneNonce).all { it.matches(Regex("[0-9a-f]{64}")) })
            val text = "framephone-link-v2\n$pin\n$headsetNonce\n$phoneNonce\n"
            return MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.US_ASCII))
                .joinToString("") { "%02x".format(it.toInt() and 255) }.take(32).uppercase().chunked(4).joinToString(" ")
        }
    }
}
