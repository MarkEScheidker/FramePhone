package com.example.framephone.link

import java.net.InetAddress
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLServerSocket
import javax.net.ssl.SSLSocket
import javax.net.ssl.X509TrustManager

/** Exercise the real provider/private key before advertising a working listener. */
object TlsSelfCheck {
    fun verify(serverContext: SSLContext, expectedPin: String) {
        val worker = Executors.newSingleThreadExecutor { task ->
            Thread(task, "phone-tls-self-check").apply { isDaemon = true }
        }
        try {
            (serverContext.serverSocketFactory.createServerSocket(0, 1, InetAddress.getLoopbackAddress()) as SSLServerSocket).use { listener ->
                listener.enabledProtocols = arrayOf("TLSv1.3")
                listener.soTimeout = 5000
                val accepted = worker.submit<Unit> {
                    (listener.accept() as SSLSocket).use { socket ->
                        socket.soTimeout = 5000
                        socket.enabledProtocols = arrayOf("TLSv1.3")
                        socket.startHandshake()
                        check(socket.session.protocol == "TLSv1.3")
                        check(socket.inputStream.read() == 0x50)
                        socket.outputStream.write(0x46)
                        socket.outputStream.flush()
                    }
                }
                // Only our exact local certificate is accepted, including in the wrong-pin regression.
                val trust = object : X509TrustManager {
                    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
                    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                        throw CertificateException("Client certificates are not used")
                    }
                    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                        if (chain.isNullOrEmpty() || Protocol.hash(chain[0].encoded) != expectedPin)
                            throw CertificateException("TLS self-check identity mismatch")
                    }
                }
                val clientContext = SSLContext.getInstance("TLSv1.3").apply { init(null, arrayOf(trust), null) }
                try {
                    (clientContext.socketFactory.createSocket(InetAddress.getLoopbackAddress(), listener.localPort) as SSLSocket).use { client ->
                        client.enabledProtocols = arrayOf("TLSv1.3")
                        client.soTimeout = 5000
                        client.startHandshake()
                        check(client.session.protocol == "TLSv1.3")
                        client.outputStream.write(0x50)
                        client.outputStream.flush()
                        check(client.inputStream.read() == 0x46)
                    }
                    accepted.get(5, TimeUnit.SECONDS)
                } finally { accepted.cancel(true) }
            }
        } finally { worker.shutdownNow() }
    }
}
