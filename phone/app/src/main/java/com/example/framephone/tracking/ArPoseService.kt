package com.example.framephone.tracking

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.opengl.EGL14
import android.opengl.EGLContext
import android.opengl.EGLDisplay
import android.opengl.EGLSurface
import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import com.example.framephone.MainActivity
import com.example.framephone.link.TelemetryService
import com.google.ar.core.Anchor
import com.google.ar.core.Config
import com.google.ar.core.CameraConfig
import com.google.ar.core.CameraConfigFilter
import com.google.ar.core.ImageMetadata
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import com.google.ar.core.exceptions.CameraNotAvailableException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.EnumSet
import kotlin.concurrent.thread

/** Armed while the activity is visible; camera work starts only for an authenticated peer. */
class ArPoseService : Service() {
    private val stopped = AtomicBoolean(false)
    private val main = Handler(Looper.getMainLooper())
    private var worker: Thread? = null
    private var overlay: MarkerOverlay? = null
    private var previousNotice = ""
    private val refresh = object : Runnable {
        override fun run() {
            if (stopped.get()) return
            try {
                overlay?.update()
                val text = when {
                    !Settings.canDrawOverlays(this@ArPoseService) -> "Overlay access required"
                    ArPoseState.overlayTimedOut -> "Alignment timed out — tap Retry"
                    else -> ArPoseState.status
                }
                if (text != previousNotice) {
                    getSystemService(NotificationManager::class.java).notify(2, notification(text))
                    previousNotice = text
                }
                main.postDelayed(this, 100)
            } catch (error: Exception) {
                stopped.set(true)
                ArPoseState.publish("error", reason = "Overlay: ${error.javaClass.simpleName}")
                stopSelf()
            }
        }
    }
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "realign") ArPoseState.requestMarker()
        if (worker != null) return START_NOT_STICKY
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("tracking", "Phone tracking", NotificationManager.IMPORTANCE_LOW))
        startForeground(2, notification("Waiting for headset"))
        ArPoseState.running = true
        ArPoseState.beginSession()
        overlay = MarkerOverlay(this)
        main.post(refresh)
        worker = thread(name = "phone-arcore") { track() }
        return START_NOT_STICKY
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(this, 2, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val retry = PendingIntent.getForegroundService(this, 3,
            Intent(this, ArPoseService::class.java).setAction("realign"), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 4,
            Intent(this, TelemetryService::class.java).setAction("stop"), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "tracking").setSmallIcon(android.R.drawable.ic_menu_compass)
            .setContentTitle("FramePhone").setContentText(text).setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Retry", retry).build())
            .addAction(Notification.Action.Builder(null, "Disconnect", stop).build()).build()
    }

    private fun track() {
        var session: Session? = null
        var anchor: Anchor? = null
        var gl: OffscreenGl? = null
        var resumed = false
        var newGeneration = true
        var previousTimestamp = 0L
        var lastFresh = SystemClock.elapsedRealtime()
        var realtimeCamera = false
        try {
            gl = OffscreenGl()
            while (!stopped.get()) {
                if (!ArPoseState.connected || !ArPoseState.unlocked) {
                    if (resumed) {
                        session?.pause()
                        resumed = false
                        // A paused anchor can remain PAUSED after screen-off on
                        // some devices. Keep the session's map, recreate its anchor
                        // and fence the resumed optical registration separately.
                        anchor?.detach()
                        anchor = null
                        newGeneration = true
                        ArPoseState.publish("paused", reason = if (ArPoseState.connected) "screen_locked" else "disconnected")
                    }
                    if (!ArPoseState.connected && session != null) {
                        anchor?.detach()
                        anchor = null
                        session?.close()
                        session = null
                        newGeneration = true
                    }
                    Thread.sleep(100)
                    continue
                }
                try {
                    if (!resumed && gl?.makeCurrent() != true) {
                        // Recover a driver-discarded offscreen context without
                        // dropping the authenticated phone/headset connection.
                        ArPoseState.publish("paused", reason = "graphics_restarting")
                        runCatching { anchor?.detach() }
                        runCatching { session?.close() }
                        anchor = null
                        session = null
                        gl?.close()
                        gl = OffscreenGl()
                        newGeneration = true
                    }
                    val activeGl = gl ?: break
                    val current = session ?: Session(this).also {
                        session = it
                        val fast = it.getSupportedCameraConfigs(CameraConfigFilter(it)
                            .setTargetFps(EnumSet.of(CameraConfig.TargetFps.TARGET_FPS_60))
                            .setDepthSensorUsage(EnumSet.of(CameraConfig.DepthSensorUsage.DO_NOT_USE)))
                        fast.minByOrNull { c -> c.imageSize.width.toLong()*c.imageSize.height }?.let { c -> it.cameraConfig = c }
                        realtimeCamera = runCatching {
                            getSystemService(CameraManager::class.java).getCameraCharacteristics(it.cameraConfig.cameraId)
                                .get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
                        }.getOrDefault(false)
                        it.configure(Config(it).apply {
                            planeFindingMode = Config.PlaneFindingMode.DISABLED
                            lightEstimationMode = Config.LightEstimationMode.DISABLED
                            depthMode = Config.DepthMode.DISABLED
                            focusMode = Config.FocusMode.AUTO
                            updateMode = Config.UpdateMode.BLOCKING
                        })
                        it.setDisplayGeometry(0, 1, 1)
                        it.setCameraTextureNames(intArrayOf(activeGl.texture))
                    }
                    if (!resumed) {
                        current.setCameraTextureNames(intArrayOf(activeGl.texture))
                        current.resume()
                        resumed = true
                        if (stopped.get()) break
                        previousTimestamp = 0L
                        lastFresh = SystemClock.elapsedRealtime()
                        if (newGeneration) { ArPoseState.beginSession(); newGeneration = false }
                    }
                    val frame = current.update()
                    if (stopped.get() || !ArPoseState.connected || !ArPoseState.unlocked) continue
                    if (frame.timestamp == 0L || frame.timestamp == previousTimestamp) {
                        if (SystemClock.elapsedRealtime() - lastFresh > 250) {
                            ArPoseState.publish("paused", reason = "no_new_camera_frames")
                            lastFresh = SystemClock.elapsedRealtime()
                        }
                        Thread.sleep(10)
                        continue
                    }
                    previousTimestamp = frame.timestamp
                    lastFresh = SystemClock.elapsedRealtime()
                    val camera = frame.camera
                    if (camera.trackingState == TrackingState.TRACKING) {
                        if (anchor?.trackingState == TrackingState.STOPPED) {
                            anchor?.detach()
                            anchor = null
                            ArPoseState.beginSession()
                        }
                        val reference = anchor ?: current.createAnchor(frame.androidSensorPose).also { anchor = it }
                        if (reference.trackingState == TrackingState.TRACKING) {
                            val relative = reference.pose.inverse().compose(frame.androidSensorPose)
                            val updated = SystemClock.elapsedRealtimeNanos()
                            val captured = if (realtimeCamera) runCatching {
                                val metadata = frame.imageMetadata
                                PoseTiming.captureCenter(true, metadata.getLong(ImageMetadata.SENSOR_TIMESTAMP),
                                    metadata.getLong(ImageMetadata.SENSOR_EXPOSURE_TIME),
                                    metadata.getLong(ImageMetadata.SENSOR_ROLLING_SHUTTER_SKEW), updated)
                            }.getOrNull() else null
                            ArPoseState.publish("tracking", relative.translation, relative.rotationQuaternion, frame.timestamp,
                                updatedAtNs = updated, captureAtNs = captured)
                        } else ArPoseState.publish("paused", reason = "anchor_not_tracking")
                    } else ArPoseState.publish("paused", reason = camera.trackingFailureReason.name)
                } catch (_: CameraNotAvailableException) {
                    ArPoseState.publish("paused", reason = "camera_in_use")
                    runCatching { session?.pause() }
                    runCatching { anchor?.detach() }
                    runCatching { session?.close() }
                    anchor = null
                    session = null
                    resumed = false
                    newGeneration = true
                    Thread.sleep(1000)
                }
            }
        } catch (error: Exception) {
            if (!stopped.get()) ArPoseState.publish("error", reason = "${error.javaClass.simpleName}: ${error.message.orEmpty()}")
        } finally {
            runCatching { anchor?.detach() }
            runCatching { session?.pause() }
            runCatching { session?.close() }
            gl?.close()
            if (!stopped.get()) stopSelf()
        }
    }

    override fun onDestroy() {
        stopped.set(true)
        main.removeCallbacks(refresh)
        overlay?.close()
        overlay = null
        ArPoseState.running = false
        if (!ArPoseState.failed) ArPoseState.publish("stopped")
        worker?.interrupt()
        super.onDestroy()
    }
}

private class OffscreenGl : AutoCloseable {
    private var display: EGLDisplay = EGL14.EGL_NO_DISPLAY
    private var context: EGLContext = EGL14.EGL_NO_CONTEXT
    private var surface: EGLSurface = EGL14.EGL_NO_SURFACE
    var texture = 0
        private set
    init {
        try {
            display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
            check(EGL14.eglInitialize(display, null, 0, null, 0)) { "Cannot initialize EGL" }
            val configs = arrayOfNulls<android.opengl.EGLConfig>(1)
            val count = IntArray(1)
            check(EGL14.eglChooseConfig(display, intArrayOf(EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT,
                EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT, EGL14.EGL_NONE), 0, configs, 0, 1, count, 0)
                && count[0] > 0) { "No offscreen EGL configuration" }
            context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE), 0)
            surface = EGL14.eglCreatePbufferSurface(display, configs[0],
                intArrayOf(EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE), 0)
            check(context != EGL14.EGL_NO_CONTEXT && surface != EGL14.EGL_NO_SURFACE &&
                EGL14.eglMakeCurrent(display, surface, surface, context)) { "Cannot create offscreen EGL context" }
            val ids = IntArray(1)
            GLES20.glGenTextures(1, ids, 0)
            texture = ids[0]
            GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, texture)
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        } catch (error: Exception) { close(); throw error }
    }
    fun makeCurrent(): Boolean = display != EGL14.EGL_NO_DISPLAY &&
        EGL14.eglMakeCurrent(display, surface, surface, context)
    override fun close() {
        if (display == EGL14.EGL_NO_DISPLAY) return
        if (texture != 0) GLES20.glDeleteTextures(1, intArrayOf(texture), 0)
        EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT)
        if (surface != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, surface)
        if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context)
        EGL14.eglTerminate(display)
        display = EGL14.EGL_NO_DISPLAY
    }
}
