package com.example.framephone

import com.example.framephone.tracking.MarkerVisibility
import org.junit.Assert.*
import org.junit.Test

class MarkerVisibilityTest {
    @Test fun automaticOverlayRequiresAnActiveUnlockedSessionAndHidesOnAcknowledgment() {
        val policy = MarkerVisibility()
        assertFalse(policy.update("scan-1", false, true, 0))
        assertTrue(policy.update("scan-1", true, true, 1_000))
        assertFalse(policy.update("scan-1", true, false, 1_500))
        assertFalse(policy.timedOut)
        assertFalse(policy.update("scan-2", false, true, 2_000))
        assertTrue(policy.update("scan-2", true, true, 3_000))
    }
    @Test fun timeoutCannotLeaveAnOpaqueOverlayCoveringOtherAppsOrAcknowledgeTracking() {
        val policy = MarkerVisibility(2_000)
        assertTrue(policy.update("scan-1", true, true, 0))
        assertFalse(policy.update("scan-1", true, true, 2_000))
        assertTrue(policy.timedOut)
        assertFalse(policy.update("scan-1", true, true, 9_000))
        assertTrue(policy.update("scan-2", true, true, 9_001))
        assertFalse(policy.timedOut)
    }
    @Test fun lateAcknowledgmentClearsTimeoutWithoutShowingAnotherMarker() {
        val policy = MarkerVisibility(1)
        policy.update("scan-1", true, true, 0)
        policy.update("scan-1", true, true, 1)
        assertFalse(policy.update("scan-1", true, false, 2))
        assertFalse(policy.timedOut)
    }
}
