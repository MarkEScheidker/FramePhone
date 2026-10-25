package com.example.framephone

import android.app.Activity
import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import android.view.View
import android.view.WindowManager
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.example.framephone.tracking.ArPoseService
import com.example.framephone.tracking.ArPoseState
import com.google.ar.core.ArCoreApk

/** A dedicated portrait surface keeps the marker square independent of text/theme settings. */
class MarkerActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private var installRequested = false
    private var trackingStarted = false
    private val arcore get() = intent.getBooleanExtra("arcore", false)
    private val checkAlignment = object : Runnable {
        override fun run() {
            if (arcore && trackingStarted && !ArPoseState.markerRequired()) {
                // Return to the previous app/Home while the camera foreground service continues.
                moveTaskToBack(true)
                finish()
            } else main.postDelayed(this, 100)
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.attributes = window.attributes.apply {
            layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
        }
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        setContentView(MarkerView(this) { finish() })
    }
    override fun onResume() {
        super.onResume()
        if (arcore && !trackingStarted) prepareTracking()
        main.removeCallbacks(checkAlignment)
        main.post(checkAlignment)
        window.decorView.postInvalidate()
    }
    private fun prepareTracking() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 10)
            return
        }
        try {
            if (ArCoreApk.getInstance().requestInstall(this, !installRequested) == ArCoreApk.InstallStatus.INSTALL_REQUESTED) {
                installRequested = true
                return
            }
            ArPoseState.requestMarker()
            startForegroundService(Intent(this, ArPoseService::class.java))
            trackingStarted = true
        } catch (error: Exception) {
            Toast.makeText(this, "Cannot start ARCore: ${error.javaClass.simpleName}", Toast.LENGTH_LONG).show()
            finish()
        }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 10) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) prepareTracking()
            else { Toast.makeText(this, "Camera permission is required for ARCore", Toast.LENGTH_LONG).show(); finish() }
        }
    }
    override fun onPause() {
        main.removeCallbacks(checkAlignment)
        Fiducial.displayed = false
        super.onPause()
    }
}

private class MarkerView(context: Context, private val exit: () -> Unit) : View(context) {
    private val paint = Paint().apply { color = Color.BLACK; isAntiAlias = false }
    init {
        contentDescription = "Large AprilTag marker. Tap to return to connection settings."
        isClickable = true
        setOnClickListener { exit() }
    }
    override fun onWindowFocusChanged(hasWindowFocus: Boolean) {
        super.onWindowFocusChanged(hasWindowFocus)
        if (!hasWindowFocus) Fiducial.displayed = false else invalidate()
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(Color.WHITE)
        // Integral device pixels: no interpolation, text, buttons or cutout overlap.
        val cell = Fiducial.cellPixels(width, height)
        val left = (width - 10 * cell) / 2
        val top = (height - 10 * cell) / 2
        Fiducial.rows.forEachIndexed { y, row -> row.forEachIndexed { x, value ->
            if (value == '1') canvas.drawRect(
                (left + x * cell).toFloat(), (top + y * cell).toFloat(),
                (left + (x + 1) * cell).toFloat(), (top + (y + 1) * cell).toFloat(), paint)
        } }
        if (hasWindowFocus()) Fiducial.drawn(context, width, height)
    }
}
