package com.example.framephone.video

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.Display
import android.view.Surface
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** A Surface feeds the hardware encoder directly; no Android pixel readback.
 * Android decides when a projection survives display-off or is revoked. */
class ScreenCaptureService : Service() {
    private val stopped = AtomicBoolean(false)
    private val main = Handler(Looper.getMainLooper())
    private var projection: MediaProjection? = null
    private var worker: Thread? = null
    @Volatile private var requestedSize = Triple(0, 0, 0)
    private var density = 1
    private val callback = object : MediaProjection.Callback() {
        override fun onStop() {
            ScreenVideo.status = "Screen capture ended — tap Share screen to resume"
            ScreenVideo.asked = true
            stopSelf()
        }
        override fun onCapturedContentResize(width: Int, height: Int) {
            val rotation = getSystemService(DisplayManager::class.java).getDisplay(Display.DEFAULT_DISPLAY).rotation
            if (width > 0 && height > 0) requestedSize = Triple(width, height, rotation)
        }
    }
    override fun onBind(intent: Intent?): IBinder? = null
    @Suppress("DEPRECATION")
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "stop") { ScreenVideo.asked = true; stopSelf(); return START_NOT_STICKY }
        if (worker != null) return START_NOT_STICKY
        val consent = if (Build.VERSION.SDK_INT >= 33) intent?.getParcelableExtra("consent", Intent::class.java)
                      else intent?.getParcelableExtra<Intent>("consent")
        if (consent == null || intent == null) { stopSelf(); return START_NOT_STICKY }
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("screen", "Screen sharing", NotificationManager.IMPORTANCE_LOW))
            manager.cancel(30)
            val stop = PendingIntent.getService(this, 31, Intent(this, ScreenCaptureService::class.java).setAction("stop"), PendingIntent.FLAG_IMMUTABLE)
            startForeground(3, Notification.Builder(this, "screen").setSmallIcon(android.R.drawable.ic_menu_slideshow)
                .setContentTitle("FramePhone screen sharing").setContentText("Encrypted stream to your paired headset")
                .setOngoing(true).addAction(Notification.Action.Builder(null, "Stop sharing", stop).build()).build(),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
            density = intent.getIntExtra("density", resources.configuration.densityDpi)
            requestedSize = Triple(intent.getIntExtra("width", 1080), intent.getIntExtra("height", 1920), intent.getIntExtra("rotation", 0))
            projection = getSystemService(MediaProjectionManager::class.java).getMediaProjection(Activity.RESULT_OK, consent)
            projection!!.registerCallback(callback, main)
            ScreenVideo.capturing = true
            ScreenVideo.status = "Starting screen encoder"
            worker = thread(name = "phone-screen-encoder") { encode() }
        } catch (error: Exception) {
            ScreenVideo.status = "Screen capture failed: ${error.javaClass.simpleName}"
            stopSelf()
        }
        return START_NOT_STICKY
    }
    private fun format(width: Int, height: Int): Pair<MediaCodec, MediaFormat> {
        val info = MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.firstOrNull {
            it.isEncoder && it.isHardwareAccelerated && it.supportedTypes.any { type -> type.equals("video/avc", true) }
        } ?: error("No hardware H.264 encoder")
        val capabilities = requireNotNull(info.getCapabilitiesForType("video/avc").videoCapabilities)
        // Preserve aspect and sharp text. Cap the first prototype's decoded size
        // to 2MP so its shared-memory and raw texture submissions stay bounded.
        val scale = minOf(1.0, 1080.0 / minOf(width, height), kotlin.math.sqrt(2_000_000.0 / (width.toDouble()*height)))
        val w = ((width*scale).toInt()/capabilities.widthAlignment*capabilities.widthAlignment).coerceAtLeast(16)
        val h = ((height*scale).toInt()/capabilities.heightAlignment*capabilities.heightAlignment).coerceAtLeast(16)
        require(capabilities.areSizeAndRateSupported(w,h,30.0)) { "Encoder does not support requested capture size" }
        val settings = MediaFormat.createVideoFormat("video/avc",w,h).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE,12_000_000.coerceIn(capabilities.bitrateRange.lower,capabilities.bitrateRange.upper))
            setInteger(MediaFormat.KEY_FRAME_RATE,30)
            setFloat(MediaFormat.KEY_MAX_FPS_TO_ENCODER,30f)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL,1)
            setLong(MediaFormat.KEY_REPEAT_PREVIOUS_FRAME_AFTER,33_333L)
            setInteger(MediaFormat.KEY_MAX_B_FRAMES,0)
            setInteger(MediaFormat.KEY_PRIORITY,0)
        }
        ScreenVideo.encoder = info.name
        return MediaCodec.createByCodecName(info.name) to settings
    }
    private fun encode() {
        var codec: MediaCodec? = null
        var surface: Surface? = null
        var display: VirtualDisplay? = null
        var size = Triple(0,0,0)
        var active = false
        try {
            while (!stopped.get()) {
                val rotation = getSystemService(DisplayManager::class.java).getDisplay(Display.DEFAULT_DISPLAY).rotation
                if (requestedSize.third != rotation) requestedSize = requestedSize.copy(third = rotation)
                val desired = requestedSize
                if (desired != size) {
                    require(desired.first > 0 && desired.second > 0 && desired.third in 0..3)
                    ScreenVideo.clearFormat()
                    display?.surface = null
                    codec?.let { runCatching { it.stop() }; it.release() }; codec = null
                    surface?.release(); surface = null
                    val (next, settings) = format(desired.first,desired.second)
                    codec = next
                    next.configure(settings,null,null,MediaCodec.CONFIGURE_FLAG_ENCODE)
                    surface = next.createInputSurface()
                    next.start()
                    if (display == null) display = projection!!.createVirtualDisplay("FramePhone screen",
                        settings.getInteger(MediaFormat.KEY_WIDTH),settings.getInteger(MediaFormat.KEY_HEIGHT),density,
                        DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,surface,null,main)
                    else { display.resize(settings.getInteger(MediaFormat.KEY_WIDTH),settings.getInteger(MediaFormat.KEY_HEIGHT),density); display.surface = surface }
                    size = desired; active = true
                }
                val current = codec!!
                val eligible = ScreenVideo.eligible()
                if (eligible != active) {
                    runCatching { current.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_SUSPEND,if (eligible) 0 else 1) }) }
                    if (eligible) current.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME,0) })
                    active = eligible
                    ScreenVideo.status = if (eligible) "Screen capture ready" else "Screen paused — waiting for tracking"
                }
                if (ScreenVideo.requestKeyframe()) current.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME,0) })
                val info = MediaCodec.BufferInfo()
                val index = current.dequeueOutputBuffer(info,10_000)
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    val output = current.outputFormat
                    val config = java.io.ByteArrayOutputStream()
                    for (key in listOf("csd-0","csd-1")) output.getByteBuffer(key)?.duplicate()?.let {
                        val bytes=ByteArray(it.remaining()); it.get(bytes); config.write(VideoWire.annexB(bytes))
                    }
                    ScreenVideo.configure(output.getInteger(MediaFormat.KEY_WIDTH),output.getInteger(MediaFormat.KEY_HEIGHT),size.third,config.toByteArray())
                    ScreenVideo.status = "Screen capture ready"
                } else if (index >= 0) {
                    try {
                        if (info.size > 0 && info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0 && active) {
                            require(info.size <= VideoWire.MAX_PACKET)
                            val buffer=current.getOutputBuffer(index)!!.duplicate()
                            buffer.position(info.offset); buffer.limit(info.offset+info.size)
                            val bytes=ByteArray(info.size); buffer.get(bytes)
                            ScreenVideo.offer(bytes,info.presentationTimeUs.coerceAtLeast(0),info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0)
                        }
                    } finally { current.releaseOutputBuffer(index,false) }
                }
            }
        } catch (error: Exception) {
            if (!stopped.get()) ScreenVideo.status = "Screen encoder stopped: ${error.javaClass.simpleName}: ${error.message?.take(100)}"
            main.post { stopSelf() }
        } finally {
            runCatching { display?.release() }
            codec?.let { runCatching { it.stop() }; runCatching { it.release() } }
            runCatching { surface?.release() }
            ScreenVideo.clearFormat()
        }
    }
    override fun onDestroy() {
        stopped.set(true)
        worker?.join(1500)
        projection?.unregisterCallback(callback)
        projection?.stop(); projection = null
        ScreenVideo.capturing = false
        if (ScreenVideo.status.startsWith("Screen streaming") || ScreenVideo.status == "Screen capture ready")
            ScreenVideo.status = "Screen sharing stopped — tap Share screen to resume"
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }
}
