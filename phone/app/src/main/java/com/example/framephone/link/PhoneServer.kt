package com.example.framephone.link

import android.content.Context
import android.os.Build
import android.os.SystemClock
import android.util.Log
import com.example.framephone.SettingsStore
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import java.security.SecureRandom
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import com.example.framephone.Fiducial
import com.example.framephone.tracking.ArPoseState
import javax.net.ssl.SSLServerSocket
import javax.net.ssl.SSLSocket
import kotlin.concurrent.thread

data class LinkStatus(val running: Boolean = false, val message: String = "Stopped",
    val address: String = "", val fingerprint: String = "", val request: String? = null,
    val peer: String = "", val paired: String? = null, val connected: Boolean = false)

class PhoneServer(private val context: Context, private val store: SettingsStore,
    private val dimensions: PhoneDimensions, private val publish: (LinkStatus) -> Unit) {
    @Volatile private var running = true
    @Volatile private var pairUntil = 0L
    @Volatile private var server: SSLServerSocket? = null
    @Volatile private var client: SSLSocket? = null
    @Volatile private var discovery: DatagramSocket? = null
    @Volatile private var pending: Approval? = null
    @Volatile private var status = LinkStatus(running = true, message = "Starting secure listener…")
    @Volatile private var stage = "startup"
    @Volatile private var tlsReady = false
    private class Approval(val id: String = UUID.randomUUID().toString()) {
        val latch = CountDownLatch(1)
        @Volatile var accepted = false
    }
    private fun update(message: String, request: String? = null, peer: String = "", fingerprint: String = "",
                       connected: Boolean = false) {
        status = status.copy(message = message, request = request, peer = peer,
            fingerprint = fingerprint, paired = store.pairedName(), connected = connected)
        if (running) publish(status)
    }
    fun openPairing() {
        pairUntil = SystemClock.elapsedRealtime() + 90000
        pending?.latch?.countDown()
        runCatching { client?.close() }
        update("Pairing open for 90 seconds. On Frame choose Find phones, then Pair.")
    }
    fun approve(id: String, accepted: Boolean) {
        pending?.takeIf { it.id == id }?.let {
            it.accepted = accepted
            it.latch.countDown()
            if (!accepted) runCatching { client?.close() }
        }
    }
    fun start(pair: Boolean) = thread(name = "phone-tls") {
        try {
            stage = "identity initialization"
            val identity = Identity()
            if (identity.replacedLegacyIdentity) {
                store.forget()
                identity.retireLegacyIdentity()
            }
            stage = "TLS self-check"
            update("Checking this phone's TLS identity…")
            val tls = identity.context()
            TlsSelfCheck.verify(tls, identity.pin)
            if (!running) return@thread
            stage = "LAN listener"
            val listener = tls.serverSocketFactory.createServerSocket(Protocol.PORT) as SSLServerSocket
            server = listener
            listener.enabledProtocols = arrayOf("TLSv1.3")
            listener.soTimeout = 1000
            val addresses = NetworkInterface.getNetworkInterfaces().toList().flatMap { it.inetAddresses.toList() }
                .filter { it is Inet4Address && !it.isLoopbackAddress }.joinToString(" / ") { it.hostAddress ?: "" }
            status = status.copy(address = addresses)
            if (pair || identity.replacedLegacyIdentity || store.pairedName() == null) openPairing()
            else update("Ready. On Frame choose Connect saved phone.")
            startDiscovery()
            while (running) {
                if (pairUntil != 0L && SystemClock.elapsedRealtime() >= pairUntil) {
                    pairUntil = 0
                    update("Pairing window expired. Tap Pair new headset to try again.")
                }
                val socket = try { listener.accept() as SSLSocket } catch (_: SocketTimeoutException) { continue }
                client = socket
                tlsReady = false
                try { serve(socket, identity.pin) }
                catch (error: Exception) {
                    // TLS details do not contain application credentials; never log inbound JSON.
                    if (stage == "TLS handshake") Log.w("FramePhone", "TLS handshake failed", error)
                    val detail = if (stage == "TLS handshake") ": ${error.message?.take(200) ?: "No details"}" else ""
                    update("Connection failed at $stage (${error.javaClass.simpleName})$detail. Reopen pairing to retry.")
                    val code = when {
                        stage == "pairing request" && SystemClock.elapsedRealtime() >= pairUntil -> "pairing_closed"
                        stage == "pairing approval" -> "pairing_rejected_or_expired"
                        stage == "reconnect authentication" -> "authentication_failed"
                        else -> "protocol_error"
                    }
                    if (tlsReady && !socket.isClosed) runCatching {
                        Protocol.write(DataOutputStream(socket.outputStream), JSONObject().put("type", "error").put("code", code))
                    }
                    runCatching { socket.close() }
                }
                finally {
                    runCatching { socket.close() }; client = null; pending = null
                    if (status.connected) update("Waiting for headset")
                }
            }
        } catch (error: Exception) {
            if (running) publish(LinkStatus(message = "Cannot start at $stage: ${error.javaClass.simpleName}: ${error.message?.take(200)}", paired = store.pairedName()))
        } finally { close() }
    }

    private fun startDiscovery() = thread(name = "phone-discovery") {
        try {
            DatagramSocket(Protocol.PORT).use { socket ->
                discovery = socket
                socket.soTimeout = 1000
                var lastReply = 0L
                while (running) {
                    val packet = DatagramPacket(ByteArray(256), 256)
                    try { socket.receive(packet) } catch (_: SocketTimeoutException) { continue }
                    if (String(packet.data, 0, packet.length, Charsets.US_ASCII) != Protocol.DISCOVERY) continue
                    if (SystemClock.elapsedRealtime() - lastReply < 100) continue
                    lastReply = SystemClock.elapsedRealtime()
                    val bytes = JSONObject().put("service", "framephone").put("version", Protocol.VERSION)
                        .put("port", Protocol.PORT).put("name", Build.MODEL.take(60))
                        .put("pairing", SystemClock.elapsedRealtime() < pairUntil).toString().toByteArray()
                    socket.send(DatagramPacket(bytes, bytes.size, packet.address, packet.port))
                }
            }
        } catch (_: Exception) { /* Manual IP entry remains available if discovery fails. */ }
    }

    private fun serve(socket: SSLSocket, pin: String) {
        stage = "TLS handshake"
        socket.enabledProtocols = arrayOf("TLSv1.3")
        socket.soTimeout = 5000
        socket.tcpNoDelay = true
        socket.startHandshake()
        tlsReady = true
        stage = "pairing request"
        val input = DataInputStream(socket.inputStream)
        val output = DataOutputStream(socket.outputStream)
        val hello = Protocol.read(input)
        require(hello.getString("type") == "hello" && hello.getInt("version") == Protocol.VERSION)
        val peer: String
        if (hello.getString("mode") == "pair") {
            require(SystemClock.elapsedRealtime() < pairUntil) { "Pairing closed" }
            peer = hello.getString("name").filter { !it.isISOControl() }.take(60)
            val nonce = ByteArray(32).also { SecureRandom().nextBytes(it) }
                .joinToString("") { "%02x".format(it.toInt() and 255) }
            val code = Protocol.pairingFingerprint(pin, hello.getString("nonce"), nonce)
            val approval = Approval()
            pending = approval
            update("Compare all four fingerprint groups with Frame, then approve both screens.", approval.id, peer, code)
            Protocol.write(output, JSONObject().put("type", "pairing").put("nonce", nonce))
            socket.soTimeout = 60000
            stage = "pairing approval"
            try {
                val confirm = Protocol.read(input)
                require(confirm.getString("type") == "confirm" && confirm.getBoolean("accepted"))
                val remaining = minOf(60000L, pairUntil - SystemClock.elapsedRealtime())
                require(remaining > 0 && approval.latch.await(remaining, TimeUnit.MILLISECONDS)
                    && approval.accepted && running && SystemClock.elapsedRealtime() < pairUntil)
                val credential = ByteArray(32).also { SecureRandom().nextBytes(it) }
                    .joinToString("") { "%02x".format(it.toInt() and 255) }
                synchronized(this) {
                    require(running)
                    store.remember(peer, credential)
                }
                pairUntil = 0
                Protocol.write(output, JSONObject().put("type", "paired").put("credential", credential))
            } finally { pending = null }
        } else {
            stage = "reconnect authentication"
            require(hello.getString("mode") == "reconnect" && store.authenticates(hello.getString("credential")))
            peer = store.pairedName() ?: error("Pairing was revoked")
        }
        require(running)
        val session = UUID.randomUUID().toString()
        stage = "sensor startup"
        val feed = SensorFeed(context)
        try {
            Protocol.write(output, JSONObject().put("type", "profile").put("version", Protocol.VERSION)
                .put("session", session).put("name", Build.MODEL).put("dimensions", dimensions.json())
                .put("clock", "android_elapsed_realtime_ns").put("axes", "android_natural_device")
                .put("sensors", feed.capabilities)
                .put("marker_state_v1", true)
                .put("headset_presence_v1", true)
                .put("arcore_pose_v1", hello.optBoolean("arcore_pose_v1"))
                .put("automatic_marker_v1", hello.optBoolean("arcore_pose_v1"))
                .apply { runCatching { Fiducial.currentProfile(context) }
                    .getOrNull()?.let { put("fiducial", it) } })
            update("Connected", peer = peer, connected = true)
            stage = "sensor streaming"
            socket.soTimeout = 8000
            val lastWrite = AtomicLong(SystemClock.elapsedRealtime())
            val alive = AtomicBoolean(true)
            val reader = thread(name = "phone-commands") {
                try {
                    while (running && alive.get()) {
                        val message = Protocol.read(input)
                        val received = SystemClock.elapsedRealtimeNanos()
                        when (message.getString("type")) {
                            "ping" -> Protocol.write(output, JSONObject().put("type", "pong").put("session", session)
                                .put("h0", message.getLong("h0")).put("p1", received)
                                .put("p2", SystemClock.elapsedRealtimeNanos()))
                            "headset_presence" -> {
                                require(message.getString("session") == session && message.get("worn") is Boolean)
                                ArPoseState.headsetPresence(message.getBoolean("worn"))
                            }
                            "alignment_accepted" -> {
                                require(hello.optBoolean("arcore_pose_v1") && message.getString("session") == session)
                                ArPoseState.acknowledge(message)
                            }
                            "alignment_lost" -> {
                                require(hello.optBoolean("arcore_pose_v1") && message.getString("session") == session)
                                ArPoseState.alignmentLost(message)
                            }
                            else -> error("Unsupported command")
                        }
                    }
                } catch (_: Exception) { alive.set(false); runCatching { socket.close() } }
            }
            val watchdog = thread(name = "phone-write-watchdog") {
                while (running && alive.get()) {
                    Thread.sleep(500)
                    if (SystemClock.elapsedRealtime() - lastWrite.get() > 3000) {
                        alive.set(false); runCatching { socket.close() }
                    }
                }
            }
            try {
                var stateAt = -500L
                var lastDisplayed: Boolean? = null
                var lastPose = ""
                while (running && alive.get()) {
                    Protocol.write(output, feed.batch(session))
                    lastWrite.set(SystemClock.elapsedRealtime())
                    if (hello.optBoolean("arcore_pose_v1")) ArPoseState.message(session)?.let { pose ->
                        val identity = "${pose.getString("generation")}:${pose.getLong("seq")}"
                        if (identity != lastPose) { Protocol.write(output, pose); lastPose = identity }
                    }
                    val now = SystemClock.elapsedRealtime()
                    val displayed = Fiducial.displayed
                    if (hello.optBoolean("marker_state_v1") && (displayed != lastDisplayed || now - stateAt >= 250)) {
                        Protocol.write(output, JSONObject().put("type", "marker_state").put("session", session)
                            .put("displayed", displayed)
                            .apply { runCatching { Fiducial.currentProfile(context) }.getOrNull()?.let { put("fiducial", it) } })
                        stateAt = now
                        lastDisplayed = displayed
                    }
                    Thread.sleep(10)
                }
            } finally {
                alive.set(false)
                runCatching { socket.close() }
                reader.join(1000)
                watchdog.join(1000)
            }
        } finally { feed.close() }
    }
    fun close() {
        synchronized(this) { running = false }
        pending?.latch?.countDown()
        runCatching { client?.close() }
        runCatching { server?.close() }
        runCatching { discovery?.close() }
    }
}
