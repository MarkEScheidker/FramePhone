package com.example.framephone.tracking

import android.app.KeyguardManager
import android.content.Context
import android.content.BroadcastReceiver
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.view.KeyEvent
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import androidx.core.content.ContextCompat
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

/** Temporary acquisition window. System navigation always lets the user leave it. */
class MarkerOverlay(private val context: Context) : AutoCloseable {
    private val windows = context.getSystemService(WindowManager::class.java)
    private val keyguard = context.getSystemService(KeyguardManager::class.java)
    private val power = context.getSystemService(PowerManager::class.java)
    private val policy = MarkerVisibility()
    private var view: View? = null

    private val navigation = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == Intent.ACTION_SCREEN_OFF) {
                ArPoseState.setUnlocked(false)
                hide()
            } else if (intent.action == Intent.ACTION_CLOSE_SYSTEM_DIALOGS && view != null &&
                intent.getStringExtra("reason") in setOf("homekey", "recentapps", "gestureNav")) dismiss()
        }
    }
    init {
        // Only listen: Android forbids applications from sending CLOSE_SYSTEM_DIALOGS.
        ContextCompat.registerReceiver(context, navigation, IntentFilter().apply {
            addAction(Intent.ACTION_CLOSE_SYSTEM_DIALOGS)
            addAction(Intent.ACTION_SCREEN_OFF)
        }, ContextCompat.RECEIVER_NOT_EXPORTED)
    }
    private fun dismiss() {
        ArPoseState.dismissMarker()
        hide()
    }
    fun update() {
        ArPoseState.setUnlocked(power.isInteractive && !keyguard.isKeyguardLocked)
        val enabled = ArPoseState.running && ArPoseState.connected && ArPoseState.unlocked &&
            ArPoseState.headsetPresent() && !ArPoseState.dismissed &&
            !ArPoseState.failed && ArPoseState.detail != "camera_in_use" && Settings.canDrawOverlays(context)
        val show = policy.update(ArPoseState.acquisitionId(), enabled, ArPoseState.markerRequired(),
            SystemClock.elapsedRealtime())
        ArPoseState.overlayTimedOut = policy.timedOut
        if (!show) { hide(); return }
        (view as? TagView)?.let {
            it.hintText = if (ArPoseState.status == "Hold still") "Hold phone steady" else ArPoseState.status
            return
        }
        val marker = TagView(context, ::dismiss)
        val params = WindowManager.LayoutParams(WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
            PixelFormat.OPAQUE).apply {
            gravity = Gravity.CENTER
            layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
            setFitInsetsTypes(0)
            title = "FramePhone alignment"
        }
        windows.addView(marker, params)
        view = marker
        marker.requestFocus()
    }

    private fun hide() {
        (view as? TagView)?.prepareToHide()
        view?.let { runCatching { windows.removeViewImmediate(it) } }
        view = null
        Fiducial.displayed = false
    }
    override fun close() {
        context.unregisterReceiver(navigation)
        hide()
    }
}

private class TagView(context: Context, private val dismiss: () -> Unit) : View(context) {
    private var closing = false
    private var focused = false
    fun prepareToHide() { closing = true }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) focused = true
        else if (focused && !closing) post {
            // Covers launchers/OEMs which do not report the Home broadcast.
            // Explicit hide disarms this path; a lock is not user cancellation.
            if (!closing && isAttachedToWindow && !hasWindowFocus() &&
                context.getSystemService(PowerManager::class.java).isInteractive &&
                !context.getSystemService(KeyguardManager::class.java).isKeyguardLocked) dismiss()
        }
    }
    private var backDispatcher: OnBackInvokedDispatcher? = null
    private var back: OnBackInvokedCallback? = null
    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (Build.VERSION.SDK_INT >= 33) post {
            if (isAttachedToWindow) {
                backDispatcher = findOnBackInvokedDispatcher()
                back = OnBackInvokedCallback { dismiss() }.also {
                    backDispatcher?.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, it)
                }
            }
        }
    }
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode == KeyEvent.KEYCODE_BACK) {
            if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) dismiss()
            return true
        }
        return super.dispatchKeyEvent(event)
    }
    override fun onTouchEvent(event: android.view.MotionEvent): Boolean {
        if (event.action == android.view.MotionEvent.ACTION_UP) { performClick(); dismiss() }
        return true
    }
    override fun performClick(): Boolean { super.performClick(); return true }

    var hintText = "Aligning"
        set(value) { if (field != value) { field = value; invalidate() } }
    private val paint = Paint().apply { color = Color.BLACK; isAntiAlias = false }
    private val hint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.DKGRAY
        textAlign = Paint.Align.CENTER
        textSize = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, 16f, resources.displayMetrics)
    }
    init {
        isFocusableInTouchMode = true
        contentDescription = "Tracking alignment. Back, Home or tap to dismiss until next unlock."
    }
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
        // Report actual layout independently of activity focus.
        if (isShown && isAttachedToWindow) Fiducial.drawn(context, width, height)
    }
    override fun onDetachedFromWindow() {
        if (Build.VERSION.SDK_INT >= 33) back?.let { backDispatcher?.unregisterOnBackInvokedCallback(it) }
        backDispatcher = null
        back = null
        Fiducial.displayed = false
        super.onDetachedFromWindow()
    }
}
