package com.example.framephone

import com.example.framephone.tracking.PoseTiming
import org.junit.Assert.*
import org.junit.Test

class PoseTimingTest {
    @Test fun centerExposureSharesTheImuClockOnlyForVerifiedRealtimeCameras() {
        assertEquals(1_015_000_000L, PoseTiming.captureCenter(true, 1_000_000_000, 20_000_000, 10_000_000, 1_030_000_000))
        assertNull(PoseTiming.captureCenter(false, 1_000_000_000, 20_000_000, 10_000_000, 1_030_000_000))
        assertNull(PoseTiming.captureCenter(true, 1_000_000_000, null, 10_000_000, 1_030_000_000))
        assertNull(PoseTiming.captureCenter(true, 1_000_000_000, 20_000_000, null, 1_030_000_000))
    }
    @Test fun staleFutureAndInvalidMetadataFallBackToUpdateTime() {
        assertNull(PoseTiming.captureCenter(true, 1_000_000_000, 20_000_000, 10_000_000, 1_010_000_000))
        assertNull(PoseTiming.captureCenter(true, 1_000_000_000, 20_000_000, 10_000_000, 1_300_000_000))
        assertNull(PoseTiming.captureCenter(true, 1_000_000_000, -1, 10_000_000, 1_030_000_000))
    }
}
