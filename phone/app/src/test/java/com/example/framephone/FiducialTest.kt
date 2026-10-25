package com.example.framephone

import org.junit.Assert.*
import org.junit.Test

class FiducialTest {
    @Test fun rotatedViewportKeepsTheNaturalPortraitGeometry() {
        assertEquals(Fiducial.viewportProfile(1080, 2400, 400.0).toString(),
            Fiducial.viewportProfile(2400, 1080, 400.0).toString())
    }
    @Test fun tagHasWhiteQuietZoneAndSquareBlackBorder() {
        assertEquals(10, Fiducial.rows.size)
        assertTrue(Fiducial.rows.all { it.length == 10 && it.first() == '0' && it.last() == '0' })
        assertEquals("0000000000", Fiducial.rows.first())
        assertEquals("0000000000", Fiducial.rows.last())
        assertEquals("0111111110", Fiducial.rows[1])
        assertEquals("0111111110", Fiducial.rows[8])
    }
    @Test fun markerUsesReportedScaleAndExplicitFrame() {
        val profile = Fiducial.profile(60.0)
        assertEquals("tag36h11", profile.getString("family"))
        assertEquals(0, profile.getInt("id"))
        assertEquals(.06, profile.getDouble("black_edge_m"), 1e-12)
        assertEquals("black_square_center", profile.getString("origin"))
        assertEquals("right_up_front", profile.getString("axes"))
        assertEquals("android_display_dpi", profile.getString("size_source"))
        assertEquals(108, Fiducial.cellPixels(1080, 2400))
        for (bad in listOf(0.0, 201.0, Double.NaN, Double.POSITIVE_INFINITY))
            assertThrows(IllegalArgumentException::class.java) { Fiducial.profile(bad) }
    }
    @Test fun fullscreenProfileMatchesTheIntegralRasterAndPortraitAspect() {
        val profile = Fiducial.displayProfile(1080, 2400, 400.0)
        assertEquals(1080, profile.getInt("screen_width_px"))
        assertEquals(2400, profile.getInt("screen_height_px"))
        assertEquals(864, profile.getInt("black_edge_px"))
        assertEquals(864.0 * 0.0254 / 400.0, profile.getDouble("black_edge_m"), 1e-12)
        assertEquals(864, Fiducial.displayProfile(1089, 2400, 400.0).getInt("black_edge_px"))
        for (bad in listOf(0.0, Double.NaN, Double.POSITIVE_INFINITY))
            assertThrows(IllegalArgumentException::class.java) { Fiducial.displayProfile(1080, 2400, bad) }
        assertThrows(IllegalArgumentException::class.java) { Fiducial.displayProfile(2400, 1080, 400.0) }
    }
}
