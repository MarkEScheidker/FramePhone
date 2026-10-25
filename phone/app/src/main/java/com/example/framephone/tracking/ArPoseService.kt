package com.example.framephone.tracking

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.opengl.EGL14
import android.opengl.EGLContext
import android.opengl.EGLDisplay
import android.opengl.EGLSurface
import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.os.IBinder
import android.os.SystemClock
import com.example.framephone.MarkerActivity
import com.google.ar.core.Anchor
import com.google.ar.core.Config
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** Owns ARCore and its small offscreen GL context independently of activity visibility. */
class ArPoseService : Service() {
    private val stopped = AtomicBoolean(false)
    private var worker: Thread? = null
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "stop") {
            stopSelf()
            return START_NOT_STICKY
        }
        if (worker != null) return START_NOT_STICKY
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("tracking", "Phone pose tracking", NotificationManager.IMPORTANCE_LOW))
        startForeground(2, notification("Initializing ARCore"))
        ArPoseState.beginSession()
        worker = thread(name = "phone-arcore") { track() }
        return START_NOT_STICKY
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(this, 2,
            Intent(this, MarkerActivity::class.java).putExtra("arcore", true),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(this, 3,
            Intent(this, ArPoseService::class.java).setAction("stop"), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "tracking").setSmallIcon(android.R.drawable.ic_menu_compass)
            .setContentTitle("FramePhone tracking").setContentText(text).setContentIntent(open)
            .setOngoing(true).addAction(Notification.Action.Builder(null, "Show marker", open).build())
            .addAction(Notification.Action.Builder(null, "Stop tracking", stop).build()).build()
    }

    private fun track() {
        var session: Session? = null
        var anchor: Anchor? = null
        var gl: OffscreenGl? = null
        try {
            gl = OffscreenGl()
            session = Session(this)
            session.configure(Config(session).apply {
                planeFindingMode = Config.PlaneFindingMode.DISABLED
                lightEstimationMode = Config.LightEstimationMode.DISABLED
                depthMode = Config.DepthMode.DISABLED
                focusMode = Config.FocusMode.AUTO
                updateMode = Config.UpdateMode.BLOCKING
            })
            session.setDisplayGeometry(0, 1, 1)
            session.setCameraTextureNames(intArrayOf(gl.texture))
            session.resume()
            var previousTimestamp = 0L
            var lastFresh = SystemClock.elapsedRealtime()
            var previousNotice = ""
            while (!stopped.get()) {
                val frame = session.update()
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
                    if (anchor == null || anchor.trackingState == TrackingState.STOPPED) {
                        anchor?.detach()
                        anchor = session.createAnchor(frame.androidSensorPose)
                        ArPoseState.beginSession()
                    }
                    if (anchor.trackingState == TrackingState.TRACKING) {
                        val relative = anchor.pose.inverse().compose(frame.androidSensorPose)
                        ArPoseState.publish("tracking", relative.translation, relative.rotationQuaternion, frame.timestamp)
                    } else ArPoseState.publish("paused", reason = "anchor_not_tracking")
                } else ArPoseState.publish("paused", reason = camera.trackingFailureReason.name)
                val notice = if (ArPoseState.markerRequired()) "Tap Show marker to align; keep the rear camera clear"
                    else "Tracking in other apps; tap Show marker to realign"
                if (notice != previousNotice) {
                    getSystemService(NotificationManager::class.java).notify(2, notification(notice))
                    previousNotice = notice
                }
            }
        } catch (error: Exception) {
            ArPoseState.publish("error", reason = "${error.javaClass.simpleName}: ${error.message.orEmpty()}")
        } finally {
            runCatching { anchor?.detach() }
            runCatching { session?.pause() }
            runCatching { session?.close() }
            gl?.close()
            if (stopped.get()) ArPoseState.publish("stopped")
            stopSelf()
        }
    }

    override fun onDestroy() {
        stopped.set(true)
        // Session.update is bounded; its owning thread releases camera/GL resources.
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
