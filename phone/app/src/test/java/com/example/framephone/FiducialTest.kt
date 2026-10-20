package com.example.framephone

import org.junit.Assert.*
import org.junit.Test

class FiducialTest {
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
}
