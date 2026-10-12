package com.example.framephone

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color as ComposeColor
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.framephone.geometry.DisplayGeometry
import kotlin.math.roundToInt

/** Uses calibrated logical pixel pitch directly; Compose density never sizes the rulers. */
@Composable
fun CalibrationRuler(geometry: DisplayGeometry, onDismiss: () -> Unit) {
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.fillMaxSize().background(ComposeColor.White).safeDrawingPadding().padding(12.dp)) {
            Text("50 mm calibration cross", color = ComposeColor.Black)
            Text("Each axis is 50 mm, with 1 mm ticks. Measure endpoint to endpoint. This checks your entered dimensions; it does not independently calibrate the phone.", color = ComposeColor.Black)
            AndroidView(modifier = Modifier.weight(1f).fillMaxWidth(), factory = { context ->
                object : View(context) {
                    private val ink = Paint().apply {
                        color = Color.BLACK
                        isAntiAlias = false
                        strokeWidth = 1f
                        textSize = 32f
                    }
                    override fun onDraw(canvas: Canvas) {
                        canvas.drawColor(Color.WHITE)
                        val lengthX = (0.05 / geometry.metersPerPixelX).roundToInt()
                        val lengthY = (0.05 / geometry.metersPerPixelY).roundToInt()
                        if (lengthX + 40 > width || lengthY + 40 > height) {
                            canvas.drawText("50 mm rulers do not fit this window", 0f, 40f, ink)
                            return
                        }
                        val left = (width - lengthX) / 2
                        val top = (height - lengthY) / 2
                        val cx = (width / 2).toFloat()
                        val cy = (height / 2).toFloat()
                        canvas.drawLine(left.toFloat(), cy, (left + lengthX).toFloat(), cy, ink)
                        canvas.drawLine(cx, top.toFloat(), cx, (top + lengthY).toFloat(), ink)
                        for (mm in 0..50) {
                            val tick = if (mm % 10 == 0) 18f else if (mm % 5 == 0) 12f else 6f
                            val x = left + (mm / 1000.0 / geometry.metersPerPixelX).roundToInt()
                            val y = top + (mm / 1000.0 / geometry.metersPerPixelY).roundToInt()
                            canvas.drawLine(x.toFloat(), cy - tick, x.toFloat(), cy + tick, ink)
                            canvas.drawLine(cx - tick, y.toFloat(), cx + tick, y.toFloat(), ink)
                        }
                    }
                }
            })
            Button(onClick = onDismiss) { Text("Close ruler") }
        }
    }
}
