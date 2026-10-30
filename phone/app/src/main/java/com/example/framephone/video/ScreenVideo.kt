package com.example.framephone.video

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.os.SystemClock
import com.example.framephone.Fiducial
import com.example.framephone.link.Protocol
import com.example.framephone.tracking.ArPoseState
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLServerSocket
import javax.net.ssl.SSLSocket
import kotlin.concurrent.thread

/** Video authentication is scoped to the live, authenticated telemetry session.
 * Network writes never run on the capture, sensor or UI thread. */
object ScreenVideo {
    data class Format(val generation: String, val width: Int, val height: Int, val rotation: Int, val config: ByteArray)
    private data class Packet(val data: ByteArray, val flags: Int, val pts: Long)
    @Volatile private var listener: SSLServerSocket? = null
    @Volatile private var session = ""
    private var token = ""
    @Volatile private var peer: SSLSocket? = null
    @Volatile private var format: Format? = null
    private val packets = ArrayBlockingQueue<Packet>(4)
    private val keyframe = AtomicBoolean(false)
    @Volatile var capturing = false
        internal set
    @Volatile var asked = false
        internal set
    @Volatile var status = "Screen sharing waits for tracking"
        internal set
    @Volatile var encoder = ""
        internal set

    fun available(): Boolean = listener?.isClosed == false
    fun eligible(): Boolean = available() && session.isNotEmpty() && ArPoseState.connected && ArPoseState.unlocked &&
        ArPoseState.headsetPresent() && !ArPoseState.dismissed &&
        !ArPoseState.markerRequired() && !Fiducial.displayed &&
        ArPoseState.message("video")?.optString("state") == "tracking"

    @Synchronized fun start(context: Context, tls: SSLContext) {
        if (listener != null) return
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("screen", "Screen sharing", NotificationManager.IMPORTANCE_LOW))
        val server = tls.serverSocketFactory.createServerSocket(VideoWire.PORT) as SSLServerSocket
        server.enabledProtocols = arrayOf("TLSv1.3")
        listener = server
        val slots = Semaphore(2)
        thread(name = "screen-listener") {
            try {
                while (!server.isClosed) {
                    val socket = server.accept() as SSLSocket
                    if (!slots.tryAcquire()) { socket.close(); continue }
                    thread(name = "screen-tls") {
                        try { serve(socket) } catch (_: Exception) {
                            if (peer === socket) status = "Video reconnecting"
                        } finally {
                            synchronized(this) { if (peer === socket) { peer = null; packets.clear() } }
                            runCatching { socket.close() }; slots.release()
                        }
                    }
                }
            } catch (_: Exception) { /* Owned listener is closed on service shutdown. */ }
        }
    }
    @Synchronized fun authorize(id: String): JSONObject {
        endSession()
        session = id
        token = ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it.toInt() and 255) }
        return JSONObject().put("version", 1).put("port", VideoWire.PORT).put("token", token)
    }
    @Synchronized fun endSession() {
        session = ""; token = ""
        disconnectVideo()
    }
    @Synchronized fun close() {
        endSession(); runCatching { listener?.close() }; listener = null
    }
    @Synchronized private fun disconnectVideo() {
        val old = peer; peer = null; packets.clear()
        runCatching { old?.shutdownInput() }; runCatching { old?.shutdownOutput() }; runCatching { old?.close() }
    }
    @Synchronized fun configure(width: Int, height: Int, rotation: Int, config: ByteArray) {
        require(width in 16..4096 && height in 16..4096 && width.toLong()*height <= 2_000_000 && rotation in 0..3)
        format = Format(UUID.randomUUID().toString(), width, height, rotation, VideoWire.annexB(config))
        disconnectVideo()
    }
    @Synchronized fun clearFormat() { format = null; disconnectVideo() }
    fun requestKeyframe(): Boolean = keyframe.getAndSet(false)
    fun offer(data: ByteArray, pts: Long, sync: Boolean) {
        if (peer == null || !eligible()) return
        val packet = Packet(VideoWire.annexB(data), if (sync) VideoWire.KEYFRAME else 0, pts)
        if (!packets.offer(packet)) {
            // P-frames have references. Reconnect at a new IDR rather than
            // silently dropping arbitrary encoded frames and corrupting playback.
            disconnectVideo()
        }
    }
    private fun serve(socket: SSLSocket) {
        socket.enabledProtocols = arrayOf("TLSv1.3"); socket.soTimeout = 5000; socket.tcpNoDelay = true
        socket.startHandshake()
        val input = DataInputStream(socket.inputStream)
        val output = DataOutputStream(socket.outputStream)
        val hello = Protocol.read(input)
        val current: Format?
        val id: String
        val waitReason: String
        synchronized(this) {
            require(session.isNotEmpty() && hello.optString("type") == "screen_video" && hello.optInt("version") == 1 &&
                hello.optString("session") == session &&
                MessageDigest.isEqual(token.toByteArray(Charsets.US_ASCII), hello.optString("token").toByteArray(Charsets.US_ASCII)))
            id = session
            current = format?.takeIf { capturing && eligible() }
            waitReason = if (!capturing) "Approve screen sharing on phone" else "Waiting for phone tracking"
            if (current != null) {
                disconnectVideo(); peer = socket; keyframe.set(true)
            }
        }
        if (current == null) {
            Protocol.write(output, JSONObject().put("type", "video_wait").put("reason", waitReason))
            return
        }
        Protocol.write(output, JSONObject().put("type", "video_ready").put("version", 1)
            .put("session", id).put("codec", "h264").put("generation", current.generation)
            .put("width", current.width).put("height", current.height).put("rotation", current.rotation))
        val wrote = AtomicLong(SystemClock.elapsedRealtime())
        val active = AtomicBoolean(true)
        val watchdog = thread(name = "screen-write-watchdog") {
            while (active.get()) {
                Thread.sleep(250)
                if (SystemClock.elapsedRealtime()-wrote.get() > 2000) { runCatching { socket.close() }; break }
            }
        }
        try {
            VideoWire.write(output, current.config, VideoWire.CONFIG, 0)
            var needSync = true
            while (peer === socket && synchronized(this) { session == id } && format?.generation == current.generation) {
                val packet = packets.poll(100, TimeUnit.MILLISECONDS)
                if (!eligible()) {
                    packets.clear(); needSync = true; keyframe.set(true)
                    VideoWire.write(output, ByteArray(0), VideoWire.HEARTBEAT, 0)
                }
                else if (packet != null && (!needSync || packet.flags == VideoWire.KEYFRAME)) {
                    VideoWire.write(output, packet.data, packet.flags, packet.pts)
                    needSync = false; status = "Screen streaming over encrypted Wi-Fi"
                } else VideoWire.write(output, ByteArray(0), VideoWire.HEARTBEAT, 1)
                wrote.set(SystemClock.elapsedRealtime())
            }
        } finally { active.set(false); watchdog.join(500) }
    }
    fun refresh(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (!eligible() || capturing || asked) { manager.cancel(30); return }
        val action = PendingIntent.getActivity(context, 30,
            android.content.Intent(context, ScreenCaptureActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        manager.notify(30, Notification.Builder(context, "screen").setSmallIcon(android.R.drawable.ic_menu_slideshow)
            .setContentTitle("FramePhone").setContentText("Tap to share your screen with the headset")
            .setContentIntent(action).setAutoCancel(true).build())
    }
}
