package com.example.framephone

import com.example.framephone.geometry.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class GeometryTest {
    private val calibration = ScreenCalibration("test", 0.072, 0.144, 1)
    private fun display(rotation: Int = 0) = DisplayGeometry(
        if (rotation % 2 == 0) 1080 else 2160,
        if (rotation % 2 == 0) 2160 else 1080,
        rotation, true, calibration,
    )
    private fun full(d: DisplayGeometry) = PixelRect(0, 0, d.widthPx, d.heightPx)
    private fun assertVector(expected: Vec3, actual: Vec3) {
        assertEquals(expected.x, actual.x, 1e-12)
        assertEquals(expected.y, actual.y, 1e-12)
        assertEquals(expected.z, actual.z, 1e-12)
    }

    @Test fun portraitOriginAndAxesHavePhysicalUnits() {
        assertVector(Vec3(0.0, 0.0), display().toPhone(PixelPoint(540, 1080)))
        assertVector(Vec3(-0.036, 0.072), display().toPhone(PixelPoint(0, 0)))
        assertVector(Vec3(0.036, -0.072), display().toPhone(PixelPoint(1080, 2160)))
    }

    @Test fun eachRotationMapsKnownScreenCornerToCanonicalPortrait() {
        // Display.getRotation(): ROTATION_90 draws clockwise on a device turned CCW.
        // D's top left is therefore P's top right at 90 degrees, bottom left at 270.
        val expected = listOf(Vec3(-0.036, 0.072), Vec3(0.036, 0.072), Vec3(0.036, -0.072), Vec3(-0.036, -0.072))
        expected.forEachIndexed { rotation, point -> assertVector(point, display(rotation).toPhone(PixelPoint(0, 0))) }
    }

    @Test fun naturalLandscapeHasExplicitPortraitReference() {
        val d = DisplayGeometry(2160, 1080, 0, false, calibration)
        assertEquals(3, d.portraitQuarterTurns)
        assertVector(Vec3(-0.036, -0.072), d.toPhone(PixelPoint(0, 0)))
        val portrait = DisplayGeometry(1080, 2160, 1, false, calibration)
        assertEquals(0, portrait.portraitQuarterTurns)
        assertVector(Vec3(-0.036, 0.072), portrait.toPhone(PixelPoint(0, 0)))
    }

    @Test fun detectorCornersExcludeQuietZone() {
        val d = display()
        val first = MarkerGeometry.layout(d, full(d), OverlayConfig()).first()
        assertEquals(PixelRect(30, 30, 330, 330), first.bounds)
        assertEquals(listOf(PixelPoint(60, 60), PixelPoint(300, 60), PixelPoint(300, 300), PixelPoint(60, 300)), first.cornersPx)
        val corners = first.cornersM(d)
        assertEquals(0.016, corners[1].x - corners[0].x, 1e-12)
        assertEquals(0.016, corners[0].y - corners[3].y, 1e-12)
    }

    @Test fun anisotropicPixelPitchUsesIndependentCellDimensions() {
        val d = DisplayGeometry(720, 2160, 0, true, calibration)
        val tag = MarkerGeometry.layout(d, full(d), OverlayConfig()).first()
        assertEquals(20, tag.cellWidthPx)
        assertEquals(30, tag.cellHeightPx)
        val corners = tag.cornersM(d)
        assertEquals(0.016, corners[1].x - corners[0].x, 1e-12)
        assertEquals(0.016, corners[0].y - corners[3].y, 1e-12)
    }

    @Test fun fractionalSizesExportRenderedSizeNotRequest() {
        val d = DisplayGeometry(1000, 2000, 0, true, calibration)
        val tag = MarkerGeometry.layout(d, full(d), OverlayConfig()).first()
        assertEquals(28, tag.cellWidthPx)
        assertEquals(0.016128, tag.cornersM(d)[1].x - tag.cornersM(d)[0].x, 1e-12)
    }

    @Test fun allSizesLayoutsRotationsAndAspectRatiosStayInUsableBounds() {
        for ((w, h) in listOf(0.072 to 0.144, 0.068 to 0.151, 0.1 to 0.16)) {
            for (rotation in 0..3) for (size in listOf(8.0, 12.0, 16.0, 20.0)) for (layout in MarkerLayout.entries) {
                val d = display(rotation).copy(calibration = ScreenCalibration("test", w, h, 1))
                val usable = PixelRect(20, 80, d.widthPx - 30, d.heightPx - 60)
                val markers = MarkerGeometry.layout(d, usable, OverlayConfig(layout, size))
                assertEquals(layout.ids, markers.map { it.id }.toSet())
                markers.forEach { assertTrue(usable.contains(it.bounds)); assertTrue(it.cornersM(d).all { p -> p.z == 0.0 }) }
            }
        }
    }

    @Test fun markerAnchorsAndRasterOrientationRemainFixedThroughDisplayRotation() {
        for (layout in MarkerLayout.entries) {
            val reference = MarkerGeometry.layout(display(), full(display()), OverlayConfig(layout))
            for (rotation in 0..3) {
                val d = display(rotation)
                val rotated = MarkerGeometry.layout(d, full(d), OverlayConfig(layout))
                reference.zip(rotated).forEach { (base, actual) ->
                    assertEquals(base.id, actual.id)
                    // Compare corner sets because export order follows current display axes.
                    val expected = base.cornersM(display())
                    actual.cornersM(d).forEach { point ->
                        assertTrue(expected.any { kotlin.math.abs(it.x - point.x) < 1e-12 && kotlin.math.abs(it.y - point.y) < 1e-12 })
                    }
                    assertEquals((4 - rotation) % 4, actual.imageRotationQuarterTurns)
                }
            }
        }
    }

    @Test fun layoutSelectionHasExplicitStableIdsAndWideBaseline() {
        val d = display()
        val two = MarkerGeometry.layout(d, full(d), OverlayConfig(MarkerLayout.TWO_DIAGONAL))
        assertEquals(listOf(0, 2), two.map { it.id })
        assertTrue(two[1].bounds.left > two[0].bounds.right)
        assertTrue(two[1].bounds.top > two[0].bounds.bottom)
        val edges = MarkerGeometry.layout(d, full(d), OverlayConfig(MarkerLayout.FOUR_EDGES))
        assertEquals(540, (edges[0].bounds.left + edges[0].bounds.right) / 2)
        assertEquals(1080, (edges[1].bounds.top + edges[1].bounds.bottom) / 2)
        assertEquals(MarkerLayout.FOUR_CORNERS, OverlayConfig().layout)
    }

    @Test fun invalidOrOverlappingLayoutsAreRejected() {
        val d = display()
        assertThrows(IllegalArgumentException::class.java) {
            MarkerGeometry.layout(d, PixelRect(0, 0, 400, 400), OverlayConfig(markerSizeMm = 20.0))
        }
        assertThrows(IllegalArgumentException::class.java) {
            MarkerGeometry.layout(d, PixelRect(-1, 0, 1080, 2160), OverlayConfig())
        }
        val tags = MarkerGeometry.layout(d, full(d), OverlayConfig())
        val overlapping = tags.map { if (it.id == 1) it.copy(bounds = tags[0].bounds) else it }
        val overlapError = assertThrows(IllegalArgumentException::class.java) {
            MarkerGeometry.validate(overlapping, full(d))
        }
        assertTrue(overlapError.message!!.contains("Markers 0 and 1 overlap"))
    }

    @Test fun orientationPolicyPausesInsteadOfConfusingPhysicalRotation() {
        assertThrows(IllegalArgumentException::class.java) {
            MarkerGeometry.layout(display(1), full(display(1)), OverlayConfig(orientation = OrientationPolicy.PORTRAIT_ONLY))
        }
        assertThrows(IllegalArgumentException::class.java) {
            MarkerGeometry.layout(display(), full(display()), OverlayConfig(orientation = OrientationPolicy.LANDSCAPE_ONLY))
        }
    }

    @Test fun rejectsNonfiniteAndImplausibleCalibrationAndConfiguration() {
        for (width in listOf(Double.NaN, Double.POSITIVE_INFINITY, 0.0, -0.1, 10.0)) {
            assertThrows(IllegalArgumentException::class.java) { ScreenCalibration("test", width, 0.144, 1) }
        }
        assertThrows(IllegalArgumentException::class.java) { OverlayConfig(markerSizeMm = Double.NaN) }
        assertThrows(IllegalArgumentException::class.java) { OverlayConfig(marginMm = -1.0) }
        assertThrows(IllegalArgumentException::class.java) { calibration.copy(portraitHeightM = 0.01) }
    }

    @Test fun everySelectedLayoutExportsOnlyItsMeasuredIds() {
        val d = display()
        val snapshot = DisplaySnapshot("test", 0, "test display", 1080, 2160, 1080, 2160, 0, true,
            999f, 999f, 420, PixelRect(0, 0, 0, 0), emptyList(), full(d))
        for (layout in MarkerLayout.entries) {
            val config = OverlayConfig(layout)
            val markers = MarkerGeometry.layout(d, full(d), config)
            val json = JSONObject(LayoutExport(snapshot, calibration, config, markers, 1234L, "test").json())
            assertEquals(layout.name, json.getString("layout"))
            val exported = json.getJSONArray("markers")
            assertEquals(layout.ids, (0 until exported.length()).map { exported.getJSONObject(it).getInt("id") }.toSet())
        }
    }

    @Test fun exportRejectsStaleGeometryFromAnotherLayout() {
        val d = display()
        val snapshot = DisplaySnapshot("test", 0, "test display", 1080, 2160, 1080, 2160, 0, true,
            999f, 999f, 420, PixelRect(0, 0, 0, 0), emptyList(), full(d))
        val stale = MarkerGeometry.layout(d, full(d), OverlayConfig(MarkerLayout.SIX_PHONE_FRAME))
        assertThrows(IllegalArgumentException::class.java) {
            LayoutExport(snapshot, calibration, OverlayConfig(), stale, 1234L, "test").json()
        }
    }

    @Test fun jsonContainsActualWindowGeometryAndVersionedUnits() {
        val d = display()
        val snapshot = DisplaySnapshot("test", 0, "test display", 1080, 2160, 1080, 2160, 0, true,
            999f, 999f, 420, PixelRect(0, 0, 0, 0), emptyList(), full(d))
        val requested = MarkerGeometry.layout(d, full(d), OverlayConfig())
        // Simulate a WindowManager shift. Export must use observed positions, not regenerate the layout.
        val actual = requested.map { it.copy(bounds = it.bounds.copy(left = it.bounds.left + 1, right = it.bounds.right + 1)) }
        val json = JSONObject(LayoutExport(snapshot, calibration, OverlayConfig(), actual, 1234L, "revision").json())
        assertEquals(1, json.getInt("layout_version"))
        assertEquals("meters", json.getString("units"))
        assertEquals(1234L, json.getLong("observed_at_elapsed_realtime_ns"))
        val marker = json.getJSONArray("markers").getJSONObject(0)
        assertEquals(61, marker.getJSONArray("corners_display_px").getJSONArray(0).getInt(0))
        assertEquals(-0.03193333333333333, marker.getJSONArray("corners_phone_m").getJSONArray(0).getDouble(0), 1e-12)
        assertEquals(0.016, marker.getJSONArray("actual_boundary_size_m").getDouble(0), 1e-12)
        assertEquals("manual_measured", json.getJSONObject("calibration").getString("status"))
        assertThrows(IllegalArgumentException::class.java) { snapshot.geometry(calibration.copy(key = "other")) }
    }
}
