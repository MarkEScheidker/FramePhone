package com.example.framephone

import android.app.Activity
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/** A dedicated portrait surface keeps the marker square independent of text/theme settings. */
class MarkerActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.attributes = window.attributes.apply { screenBrightness = 1f }
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        setContentView(MarkerView(this) { finish() })
    }
}

private class MarkerView(context: Context, private val exit: () -> Unit) : View(context) {
    private val paint = Paint().apply { color = Color.BLACK; isAntiAlias = false }
    init {
        contentDescription = "Large AprilTag marker. Tap to return to connection settings."
        isClickable = true
        setOnClickListener { exit() }
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
    }
}
