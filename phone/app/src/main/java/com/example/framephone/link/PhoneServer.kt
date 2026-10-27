package com.example.framephone.link

import android.content.Context
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.annotation.SuppressLint
import android.os.Build
import android.os.SystemClock
import android.util.Log
import com.example.framephone.SettingsStore
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import com.example.framephone.Fiducial
import com.example.framephone.tracking.ArPoseState
import com.example.framephone.bluetooth.BluetoothPose
import javax.net.ssl.SSLServerSocket
import javax.net.ssl.SSLSocket
import kotlin.concurrent.thread

data class LinkStatus(val running: Boolean = false, val message: String = "Stopped",
    val address: String = "", val paired: String? = null, val connected: Boolean = false)

class PhoneServer(private val context: Context, private val store: SettingsStore,
    private val dimensions: PhoneDimensions, private val publish: (LinkStatus) -> Unit) {
    @Volatile private var running = true
    @Volatile private var server: SSLServerSocket? = null
    @Volatile private var client: SSLSocket? = null
    @Volatile private var status = LinkStatus(running = true, message = "Starting secure listener…")
    @Volatile private var stage = "startup"
    @Volatile private var tlsReady = false
    private fun update(message: String, connected: Boolean = false) {
        status = status.copy(message = message, paired = store.pairedName(), connected = connected)
        if (running) publish(status)
    }
    fun start() = thread(name = "phone-tls") {
        try {
            stage = "identity initialization"
            val identity = Identity()
            if (identity.replacedLegacyIdentity) {
                store.resetApplicationTrust()
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
            update("Waiting for headset over Bluetooth")
            while (running) {
                // Refresh the BLE route while waiting for TLS, so a Wi-Fi
                // reconnect/IP change does not require restarting either app.
                val endpoint = NetworkInterface.getNetworkInterfaces().toList()
                    .sortedBy { if (it.name.startsWith("wlan")) 0 else 1 }
                    .flatMap { it.inetAddresses.toList() }.firstOrNull { it is Inet4Address && it.isSiteLocalAddress }
                    ?.hostAddress.orEmpty()
                BluetoothPose.identity(identity.pin, endpoint)
                if (endpoint.isEmpty() && !status.message.startsWith("Wi-Fi unavailable"))
                    update("Wi-Fi unavailable — connect both devices to the same network")
                else if (endpoint.isNotEmpty() && status.message.startsWith("Wi-Fi unavailable"))
                    update("Waiting for headset over Bluetooth")
                val socket = try { listener.accept() as SSLSocket } catch (_: SocketTimeoutException) { continue }
                client = socket
                tlsReady = false
                try { serve(socket) }
                catch (error: Exception) {
                    // TLS details do not contain application credentials; never log inbound JSON.
                    if (stage == "TLS handshake") Log.w("FramePhone", "TLS handshake failed", error)
                    val detail = if (stage == "TLS handshake") ": ${error.message?.take(200) ?: "No details"}" else ""
                    update("Connection failed at $stage (${error.javaClass.simpleName})$detail. Reconnecting automatically.")
                    val code = if (stage == "reconnect authentication") "authentication_failed" else "protocol_error"
                    if (tlsReady && !socket.isClosed) runCatching {
                        Protocol.write(DataOutputStream(socket.outputStream), JSONObject().put("type", "error").put("code", code))
                    }
                    runCatching { socket.close() }
                }
                finally {
                    runCatching { socket.close() }; client = null
                    if (status.connected) update("Waiting for headset")
                }
            }
        } catch (error: Exception) {
            if (running) publish(LinkStatus(message = "Cannot start at $stage: ${error.javaClass.simpleName}: ${error.message?.take(200)}", paired = store.pairedName()))
        } finally { close() }
    }

    @SuppressLint("MissingPermission")
    private fun companionBonded(): Boolean {
        val address = store.bluetoothAddress() ?: return false
        return context.getSystemService(BluetoothManager::class.java).adapter
            ?.getRemoteDevice(address)?.bondState == BluetoothDevice.BOND_BONDED
    }
    fun disconnectClient() { runCatching { client?.close() } }

    private fun serve(socket: SSLSocket) {
        stage = "TLS handshake"
        socket.enabledProtocols = arrayOf("TLSv1.3")
        socket.soTimeout = 5000
        socket.tcpNoDelay = true
        socket.startHandshake()
        tlsReady = true
        stage = "session request"
        val input = DataInputStream(socket.inputStream)
        val output = DataOutputStream(socket.outputStream)
        val hello = Protocol.read(input)
        require(hello.getString("type") == "hello" && hello.getInt("version") == Protocol.VERSION)
        stage = "reconnect authentication"
        require(hello.getString("mode") == "reconnect" && companionBonded() && store.authenticates(hello.getString("credential"))) {
            "Pair over Bluetooth first"
        }
        require(running && store.pairedName() != null)
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
                .put("bluetooth_pose_v1", true)
                .put("arcore_pose_v1", hello.optBoolean("arcore_pose_v1"))
                .put("automatic_marker_v1", hello.optBoolean("arcore_pose_v1"))
                .apply { runCatching { Fiducial.currentProfile(context) }
                    .getOrNull()?.let { put("fiducial", it) } })
            BluetoothPose.session(session)
            update("Connected", connected = true)
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
                var wifiPoseAt = 0L
                var wifiState = ""
                while (running && alive.get()) {
                    Protocol.write(output, feed.batch(session))
                    lastWrite.set(SystemClock.elapsedRealtime())
                    if (hello.optBoolean("arcore_pose_v1")) ArPoseState.message(session)?.let { pose ->
                        val identity = "${pose.getString("generation")}:${pose.getLong("seq")}"
                        if (identity != lastPose) {
                            val bluetooth = BluetoothPose.isBound()
                            val state = "${pose.getString("generation")}:${pose.getString("acquisition")}:${pose.getString("state")}"
                            val nowPose = SystemClock.elapsedRealtime()
                            if (!bluetooth || state != wifiState || nowPose-wifiPoseAt >= 200) {
                                Protocol.write(output, pose)
                                wifiPoseAt = nowPose; wifiState = state
                            }
                            lastPose = identity
                        }
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
        } finally { BluetoothPose.session(null); feed.close() }
    }
    fun close() {
        synchronized(this) { running = false }
        runCatching { client?.close() }
        runCatching { server?.close() }
    }
}
