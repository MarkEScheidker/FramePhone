package com.example.framephone.geometry

import com.example.framephone.markers.Tag36h11
import org.json.JSONArray
import org.json.JSONObject

/** Immutable snapshot of a completed WindowManager layout; never exported from requested positions. */
data class LayoutExport(
    val display: DisplaySnapshot,
    val calibration: ScreenCalibration,
    val config: OverlayConfig,
    val markers: List<RenderedMarker>,
    val observedAtElapsedRealtimeNs: Long,
    val revision: String,
) {
    fun json(): String {
        val geometry = display.geometry(calibration)
        MarkerGeometry.validate(markers, display.rotationStableMarkerBounds())
        require(markers.map { it.id }.toSet() == config.layout.ids) { "Measured IDs disagree with configured layout" }
        return JSONObject().apply {
            put("schema", "framephone.phone-layout")
            put("layout_version", 1)
            put("revision", revision)
            put("units", "meters")
            put("family", Tag36h11.FAMILY)
            put("family_source", Tag36h11.SOURCE)
            put("layout", config.layout.name)
            put("orientation_policy", config.orientation.name)
            put("requested_marker_size_m", config.markerSizeMm / 1000)
            put("requested_margin_m", config.marginMm / 1000)
            put("size_definition", "detector_boundary_excluding_white_quiet_zone")
            put("corner_order", JSONArray(listOf("top_left", "top_right", "bottom_right", "bottom_left")))
            put("corner_reference", "rendered_tag_image_pixel_edges")
            put("observed_at_elapsed_realtime_ns", observedAtElapsedRealtimeNs)
            put("timestamp_domain", "android_elapsed_realtime_ns_not_openxr")
            put("calibration", JSONObject().apply {
                put("status", "manual_measured")
                put("version", 1)
                put("configuration_key", calibration.key)
                put("measured_at_epoch_ms", calibration.measuredAtEpochMs)
                put("portrait_width_m", calibration.portraitWidthM)
                put("portrait_height_m", calibration.portraitHeightM)
                put("uncertainty_m", JSONObject.NULL)
            })
            put("display", JSONObject().apply {
                put("id", display.displayId)
                put("name", display.displayName)
                put("physical_mode_px", JSONArray(listOf(display.physicalWidthPx, display.physicalHeightPx)))
                put("logical_px", JSONArray(listOf(display.logicalWidthPx, display.logicalHeightPx)))
                put("rotation_surface", display.rotation)
                put("natural_portrait", display.naturalPortrait)
                put("portrait_quarter_turns", geometry.portraitQuarterTurns)
                put("reported_xdpi", display.xdpi.toDouble())
                put("reported_ydpi", display.ydpi.toDouble())
                put("density_dpi", display.densityDpi)
                put("insets_ltrb_px", rect(display.insets))
                put("usable_bounds_px", rect(display.usable))
                put("rotation_stable_marker_bounds_px", rect(display.rotationStableMarkerBounds()))
                put("rounded_corner_radius_px", display.roundedCornerRadiusPx)
                put("cutout_bounds_px", JSONArray(display.cutouts.map(::rect)))
                put("meters_per_pixel_xy", JSONArray(listOf(geometry.metersPerPixelX, geometry.metersPerPixelY)))
                // Quaternion [x,y,z,w] for the right-handed rotation D -> P.
                val half = -geometry.portraitQuarterTurns * Math.PI / 4
                put("T_PD", JSONObject().put("translation_m", JSONArray(listOf(0, 0, 0)))
                    .put("quaternion_xyzw", JSONArray(listOf(0.0, 0.0, kotlin.math.sin(half), kotlin.math.cos(half)))))
            })
            put("markers", JSONArray(markers.map { marker -> JSONObject().apply {
                put("id", marker.id)
                put("image_rotation_clockwise_deg", marker.imageRotationQuarterTurns * 90)
                put("window_bounds_px", rect(marker.bounds))
                put("cell_size_px", JSONArray(listOf(marker.cellWidthPx, marker.cellHeightPx)))
                put("quiet_zone_cells", 1)
                put("corners_display_px", JSONArray(marker.cornersPx.map { JSONArray(listOf(it.x, it.y)) }))
                put("corners_phone_m", JSONArray(marker.cornersM(geometry).map { JSONArray(listOf(it.x, it.y, it.z)) }))
                put("actual_boundary_size_m", JSONArray(listOf(marker.cellWidthPx * 8 * geometry.metersPerPixelX,
                    marker.cellHeightPx * 8 * geometry.metersPerPixelY)))
            } }))
        }.toString(2)
    }

    private fun rect(r: PixelRect) = JSONArray(listOf(r.left, r.top, r.right, r.bottom))
}
