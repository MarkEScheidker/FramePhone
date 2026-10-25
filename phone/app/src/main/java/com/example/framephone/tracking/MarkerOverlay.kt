package com.example.framephone.tracking

import android.app.KeyguardManager
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.os.PowerManager
import android.os.SystemClock
import android.provider.Settings
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import com.example.framephone.Fiducial

/** Main-thread, non-focusable acquisition window; removing it never changes the foreground app. */
class MarkerOverlay(private val context: Context) : AutoCloseable {
    private val windows = context.getSystemService(WindowManager::class.java)
    private val keyguard = context.getSystemService(KeyguardManager::class.java)
    private val power = context.getSystemService(PowerManager::class.java)
    private val policy = MarkerVisibility()
    private var view: View? = null

    fun update() {
        ArPoseState.setUnlocked(power.isInteractive && !keyguard.isKeyguardLocked)
        val enabled = ArPoseState.running && ArPoseState.connected && ArPoseState.unlocked &&
            !ArPoseState.failed && ArPoseState.detail != "camera_in_use" && Settings.canDrawOverlays(context)
        val show = policy.update(ArPoseState.acquisitionId(), enabled, ArPoseState.markerRequired(),
            SystemClock.elapsedRealtime())
        ArPoseState.overlayTimedOut = policy.timedOut
        if (!show) { hide(); return }
        (view as? TagView)?.let {
            it.hintText = if (ArPoseState.status == "Hold still") "Hold phone steady" else ArPoseState.status
            return
        }
        val marker = TagView(context)
        val params = WindowManager.LayoutParams(WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
            PixelFormat.OPAQUE).apply {
            gravity = Gravity.CENTER
            layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
            setFitInsetsTypes(0)
            title = "FramePhone alignment"
        }
        windows.addView(marker, params)
        view = marker
    }

    private fun hide() {
        view?.let { runCatching { windows.removeViewImmediate(it) } }
        view = null
        Fiducial.displayed = false
    }
    override fun close() = hide()
}

private class TagView(context: Context) : View(context) {
    var hintText = "Hold phone steady"
        set(value) { if (field != value) { field = value; invalidate() } }
    private val paint = Paint().apply { color = Color.BLACK; isAntiAlias = false }
    private val hint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.DKGRAY
        textAlign = Paint.Align.CENTER
        textSize = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, 16f, resources.displayMetrics)
    }
    init { contentDescription = "Tracking alignment. Hold still." }
    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(Color.WHITE)
        val cell = Fiducial.cellPixels(width, height)
        // Keep decoded marker axes fixed to Android's natural-device axes,
        // even when the foreground app rotates its logical display.
        canvas.save()
        canvas.translate(width/2f, height/2f)
        canvas.rotate(-90f * (display?.rotation ?: 0))
        val left = -5 * cell
        val top = -5 * cell
        Fiducial.rows.forEachIndexed { y, row -> row.forEachIndexed { x, value ->
            if (value == '1') canvas.drawRect((left + x*cell).toFloat(), (top + y*cell).toFloat(),
                (left + (x+1)*cell).toFloat(), (top + (y+1)*cell).toFloat(), paint)
        } }
        canvas.restore()
        val gap = 64 * resources.displayMetrics.density
        if ((height - 10*cell)/2 > gap)
            canvas.drawText(hintText, width/2f, height - gap/2, hint)
        // A non-focusable overlay never owns activity focus. Report actual layout,
        // rather than requiring the activity focus signal used by the old marker.
        if (isShown && isAttachedToWindow) Fiducial.drawn(context, width, height)
    }
    override fun onDetachedFromWindow() {
        Fiducial.displayed = false
        super.onDetachedFromWindow()
    }
}
