package com.example.framephone

import android.content.Context
import android.view.WindowManager
import org.json.JSONObject

/** tag36h11 ID 0, apriltag_to_image output: 1=black, 0=white.
 * Includes the entire 8-cell black square and one white quiet cell each side.
 * AprilTag codeword data: BSD-2-Clause; see assets/APRILTAG_LICENSE.txt.
 */
object Fiducial {
    @Volatile var displayed = false
    @Volatile private var drawnProfile: String? = null
    val rows = listOf(
        "0000000000", "0111111110", "0100101010", "0110001010", "0110011110",
        "0101011110", "0110100110", "0111101110", "0111111110", "0000000000",
    )
    fun profile(edgeMm: Double): JSONObject {
        require(edgeMm.isFinite() && edgeMm in 10.0..200.0)
        return JSONObject().put("family", "tag36h11").put("id", 0)
            .put("black_edge_m", edgeMm / 1000.0)
            .put("size_source", "android_display_dpi")
            .put("origin", "black_square_center").put("axes", "right_up_front")
    }
    fun cellPixels(width: Int, height: Int): Int = (minOf(width, height) / 10).coerceAtLeast(1)
    fun displayProfile(width: Int, height: Int, xdpi: Double): JSONObject {
        require(width in 100..10000 && height in width..10000)
        require(xdpi.isFinite() && xdpi in 50.0..2000.0) { "Invalid reported display DPI" }
        val blackPixels = cellPixels(width, height) * 8
        return profile(blackPixels * 25.4 / xdpi)
            .put("screen_width_px", width).put("screen_height_px", height)
            .put("black_edge_px", blackPixels)
    }
    fun drawn(context: Context, width: Int, height: Int) {
        drawnProfile = runCatching {
            viewportProfile(width, height, context.resources.displayMetrics.xdpi.toDouble()).toString()
        }.getOrNull()
        displayed = drawnProfile != null
    }
    fun currentProfile(context: Context): JSONObject =
        // Keep the last actual portrait raster after hiding it. Another app's
        // display rotation must not change the geometry of an ARCore session.
        if (drawnProfile != null) JSONObject(drawnProfile!!) else automaticProfile(context)
    fun automaticProfile(context: Context): JSONObject {
        val bounds = context.getSystemService(WindowManager::class.java).maximumWindowMetrics.bounds
        val xdpi = context.resources.displayMetrics.xdpi.toDouble()
        return viewportProfile(bounds.width(), bounds.height(), xdpi)
    }
    fun viewportProfile(width: Int, height: Int, xdpi: Double): JSONObject =
        displayProfile(minOf(width, height), maxOf(width, height), xdpi)
}
