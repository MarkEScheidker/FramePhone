package com.example.framephone.geometry

import android.content.Context
import android.graphics.Rect
import android.os.Build
import android.util.DisplayMetrics
import android.view.Display
import android.view.RoundedCorner
import android.view.WindowInsets
import android.view.WindowManager

data class DisplaySnapshot(
    val key: String,
    val displayId: Int,
    val displayName: String,
    val physicalWidthPx: Int,
    val physicalHeightPx: Int,
    val logicalWidthPx: Int,
    val logicalHeightPx: Int,
    val rotation: Int,
    val naturalPortrait: Boolean,
    val xdpi: Float,
    val ydpi: Float,
    val densityDpi: Int,
    val insets: PixelRect,
    val cutouts: List<PixelRect>,
    val usable: PixelRect,
    val roundedCornerRadiusPx: Int = 0,
) {
    fun geometry(calibration: ScreenCalibration) = DisplayGeometry(
        logicalWidthPx, logicalHeightPx, rotation, naturalPortrait, calibration,
    ).also { require(calibration.key == key) { "Recalibrate this display configuration" } }

    /** Stable physical panel bounds; system bar insets move with UI rotation, rounded corners do not. */
    fun rotationStableMarkerBounds(): PixelRect {
        val radius = roundedCornerRadiusPx.coerceAtLeast(0)
        return PixelRect(radius, radius, logicalWidthPx - radius, logicalHeightPx - radius)
    }

    companion object {
        @Suppress("DEPRECATION")
        fun read(context: Context, display: Display): DisplaySnapshot {
            val wm = context.getSystemService(WindowManager::class.java)
            val metrics = wm.maximumWindowMetrics
            val bounds = metrics.bounds
            require(bounds.left == 0 && bounds.top == 0) { "Nonzero display origin is unsupported" }
            val dm = DisplayMetrics().also(display::getRealMetrics)
            val rotation = display.rotation
            val naturalPortrait = if (rotation % 2 == 0) bounds.width() <= bounds.height() else bounds.height() <= bounds.width()
            val mode = display.mode
            val insets = metrics.windowInsets.getInsetsIgnoringVisibility(
                WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout(),
            )
            val cutout = metrics.windowInsets.displayCutout
            val waterfall = cutout?.waterfallInsets
            val l = maxOf(insets.left, waterfall?.left ?: 0)
            val t = maxOf(insets.top, waterfall?.top ?: 0)
            val r = maxOf(insets.right, waterfall?.right ?: 0)
            val b = maxOf(insets.bottom, waterfall?.bottom ?: 0)
            // Conservatively avoid corner arcs on every edge, including landscape navigation.
            val radius = listOf(RoundedCorner.POSITION_TOP_LEFT, RoundedCorner.POSITION_TOP_RIGHT,
                RoundedCorner.POSITION_BOTTOM_RIGHT, RoundedCorner.POSITION_BOTTOM_LEFT)
                .maxOf { display.getRoundedCorner(it)?.radius ?: 0 }
            val key = listOf(Build.MANUFACTURER, Build.MODEL, display.displayId, display.name,
                minOf(mode.physicalWidth, mode.physicalHeight), maxOf(mode.physicalWidth, mode.physicalHeight),
                minOf(bounds.width(), bounds.height()), maxOf(bounds.width(), bounds.height()), naturalPortrait).joinToString("|")
            return DisplaySnapshot(key, display.displayId, display.name, mode.physicalWidth, mode.physicalHeight,
                bounds.width(), bounds.height(), rotation, naturalPortrait, dm.xdpi, dm.ydpi, dm.densityDpi,
                PixelRect(l, t, r, b), cutout?.boundingRects.orEmpty().map(Rect::pixels),
                PixelRect(maxOf(l, radius), maxOf(t, radius), bounds.width() - maxOf(r, radius),
                    bounds.height() - maxOf(b, radius)), radius)
        }
    }
}

private fun Rect.pixels() = PixelRect(left, top, right, bottom)
