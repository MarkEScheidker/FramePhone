package com.example.framephone

import com.example.framephone.link.Protocol
import com.example.framephone.link.TlsSelfCheck
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.security.KeyStore
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException

class TlsSelfCheckTest {
    @Test fun selfCheckCompletesTls13AndRejectsAnotherCertificate() {
        val folder = Files.createTempDirectory("framephone-tls-test").toFile()
        try {
            val executable = if (System.getProperty("os.name").orEmpty().startsWith("Windows")) "keytool.exe" else "keytool"
            val keytool = File(System.getProperty("java.home"), "bin/$executable")
            val output = File(folder, "identity.p12")
            val process = ProcessBuilder(keytool.absolutePath, "-genkeypair", "-alias", "test",
                "-keyalg", "EC", "-groupname", "secp256r1", "-sigalg", "SHA256withECDSA",
                "-dname", "CN=FramePhone test", "-validity", "1", "-storetype", "PKCS12",
                "-keystore", output.absolutePath, "-storepass", "test-only-password", "-noprompt")
                .redirectErrorStream(true).start()
            val details = process.inputStream.bufferedReader().use { it.readText() }
            assertEquals(details, 0, process.waitFor())
            val password = "test-only-password".toCharArray()
            val store = KeyStore.getInstance("PKCS12").apply { output.inputStream().use { load(it, password) } }
            val managers = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply { init(store, password) }
            val server = SSLContext.getInstance("TLSv1.3").apply { init(managers.keyManagers, null, null) }
            val pin = Protocol.hash(store.getCertificate("test").encoded)
            TlsSelfCheck.verify(server, pin)
            assertThrows(SSLException::class.java) { TlsSelfCheck.verify(server, "0".repeat(64)) }
        } finally { folder.deleteRecursively() }
    }
}
