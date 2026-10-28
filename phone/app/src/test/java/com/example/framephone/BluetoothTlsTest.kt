package com.example.framephone

import com.example.framephone.bluetooth.BluetoothTls
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.file.Files
import java.security.KeyStore
import java.security.cert.X509Certificate
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

class BluetoothTlsTest {
    @Test fun tls13CarriesFragmentedBinaryMessagesAndRejectsTampering() {
        val folder = Files.createTempDirectory("framephone-ble-tls").toFile()
        try {
            val keytool = File(System.getProperty("java.home"), "bin/"+
                if (System.getProperty("os.name").orEmpty().startsWith("Windows")) "keytool.exe" else "keytool")
            val file = File(folder, "identity.p12")
            val process = ProcessBuilder(keytool.path, "-genkeypair", "-alias", "phone", "-keyalg", "EC",
                "-groupname", "secp256r1", "-dname", "CN=Bluetooth TLS test", "-validity", "1",
                "-storetype", "PKCS12", "-keystore", file.path, "-storepass", "test-password", "-noprompt")
                .redirectErrorStream(true).start()
            val details = process.inputStream.bufferedReader().readText()
            assertEquals(details, 0, process.waitFor())
            val keys = KeyStore.getInstance("PKCS12").apply { file.inputStream().use { load(it, "test-password".toCharArray()) } }
            val managers = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply { init(keys, "test-password".toCharArray()) }
            val server = BluetoothTls(SSLContext.getInstance("TLSv1.3").apply { init(managers.keyManagers, null, null) })
            val trust = object : X509TrustManager {
                override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
                override fun checkClientTrusted(chain: Array<X509Certificate>, type: String) {}
                override fun checkServerTrusted(chain: Array<X509Certificate>, type: String) {}
            }
            val client = SSLContext.getInstance("TLSv1.3").apply { init(null, arrayOf<TrustManager>(trust), null) }
                .createSSLEngine().apply { useClientMode = true; enabledProtocols = arrayOf("TLSv1.3"); beginHandshake() }
            val incoming = ByteBuffer.allocate(65536)
            val sink = ByteBuffer.allocate(65536)
            var received = listOf<ByteArray>()
            repeat(100) {
                while (client.delegatedTask?.also { it.run() } != null) {}
                val wire = ByteBuffer.allocate(65536)
                client.wrap(ByteBuffer.allocate(0), wire)
                val bytes = wire.array().copyOf(wire.position())
                bytes.toList().chunked(7).forEach { server.receive(it.toByteArray()) }
                incoming.put(server.take()).flip()
                while (incoming.hasRemaining()) {
                    val result = client.unwrap(incoming, sink)
                    while (client.delegatedTask?.also { it.run() } != null) {}
                    if (result.bytesConsumed() == 0) break
                }
                incoming.compact()
            }
            assertTrue(server.ready)
            assertEquals("TLSv1.3", client.session.protocol)
            val payload = byteArrayOf(1)+ByteArray(250) { it.toByte() }
            val framed = ByteBuffer.allocate(payload.size+4).apply { putInt(payload.size); put(payload); flip() }
            val encrypted = ByteBuffer.allocate(65536)
            client.wrap(framed, encrypted)
            val bytes = encrypted.array().copyOf(encrypted.position())
            bytes.toList().chunked(3).forEach { received += server.receive(it.toByteArray()) }
            assertEquals(1, received.size)
            assertArrayEquals(payload, received.single())
            val corrupt = ByteBuffer.allocate(65536)
            framed.rewind(); client.wrap(framed, corrupt)
            val damaged = corrupt.array().copyOf(corrupt.position())
            damaged[damaged.lastIndex] = (damaged.last().toInt() xor 1).toByte()
            assertThrows(javax.net.ssl.SSLException::class.java) { server.receive(damaged) }
        } finally { folder.deleteRecursively() }
    }

    @Test fun hashCodeIsBoundToCertificateAndBothNonces() {
        val value = BluetoothTls.code("a".repeat(64), "b".repeat(64), "c".repeat(64))
        assertEquals("F204 0086 70A3 419F ED01 B16D FA26 377D", value)
        assertNotEquals(value, BluetoothTls.code("d".repeat(64), "b".repeat(64), "c".repeat(64)))
        assertNotEquals(value, BluetoothTls.code("a".repeat(64), "b".repeat(64), "d".repeat(64)))
    }
}
