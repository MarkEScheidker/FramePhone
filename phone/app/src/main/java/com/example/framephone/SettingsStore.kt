package com.example.framephone

import android.content.Context
import androidx.core.content.edit
import com.example.framephone.geometry.*
import java.security.MessageDigest

class SettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences("fiducials_v1", Context.MODE_PRIVATE)
    fun config(): OverlayConfig = runCatching {
        OverlayConfig(
            MarkerLayout.valueOf(prefs.getString("layout", MarkerLayout.FOUR_CORNERS.name)!!),
            prefs.getString("size", "16.0")!!.toDouble(),
            prefs.getString("margin", "2.0")!!.toDouble(),
            OrientationPolicy.valueOf(prefs.getString("orientation", OrientationPolicy.FOLLOW_DISPLAY.name)!!),
        )
    }.getOrDefault(OverlayConfig())

    fun save(config: OverlayConfig) {
        prefs.edit {
            putString("layout", config.layout.name)
            putString("size", config.markerSizeMm.toString())
            putString("margin", config.marginMm.toString())
            putString("orientation", config.orientation.name)
        }
    }

    private fun prefix(key: String) = MessageDigest.getInstance("SHA-256").digest(key.toByteArray())
        .joinToString("") { "%02x".format(it) }

    fun calibration(key: String): ScreenCalibration? = runCatching {
        val p = prefix(key)
        ScreenCalibration(key, prefs.getString("$p.width", null)!!.toDouble(),
            prefs.getString("$p.height", null)!!.toDouble(), prefs.getLong("$p.time", 0))
    }.getOrNull()

    fun save(calibration: ScreenCalibration) {
        val p = prefix(calibration.key)
        prefs.edit {
            putString("$p.width", calibration.portraitWidthM.toString())
            putString("$p.height", calibration.portraitHeightM.toString())
            putLong("$p.time", calibration.measuredAtEpochMs)
        }
    }
}
