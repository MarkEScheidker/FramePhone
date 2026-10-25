package com.example.framephone

import com.example.framephone.tracking.ArPoseState
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class ArPoseStateTest {
    @Before fun begin() { ArPoseState.setConnected(false); ArPoseState.setUnlocked(true); ArPoseState.beginSession() }
    private fun pose(time: Long = 1_000_000_000L) {
        ArPoseState.publish("tracking", floatArrayOf(0f, 0f, 0f), floatArrayOf(0f, 0f, 0f, 1f), updatedAtNs = time)
    }
    private fun acknowledgment(): JSONObject {
        val sample = ArPoseState.message("connection-1")!!
        return JSONObject().put("generation", sample.getString("generation"))
            .put("acquisition", sample.getString("acquisition"))
    }
    @Test fun onlyFreshMatchingAcquisitionCanHideMarker() {
        pose()
        val ack = acknowledgment()
        assertFalse(ArPoseState.acknowledge(JSONObject(ack.toString()).put("acquisition", "old"), 1_010_000_000L))
        assertFalse(ArPoseState.acknowledge(ack, 999_999_999L))
        assertFalse(ArPoseState.acknowledge(ack, 1_250_000_001L))
        assertTrue(ArPoseState.markerRequired())
        assertTrue(ArPoseState.acknowledge(ack, 1_010_000_000L))
        assertFalse(ArPoseState.markerRequired())
        assertFalse(ArPoseState.acknowledge(ack, 1_020_000_000L))
    }
    @Test fun lossAndExplicitReacquisitionFenceOldAcknowledgments() {
        pose()
        val old = acknowledgment()
        assertTrue(ArPoseState.acknowledge(old, 1_010_000_000L))
        ArPoseState.publish("paused", updatedAtNs = 1_020_000_000L)
        assertTrue(ArPoseState.markerRequired())
        pose(1_030_000_000L)
        assertFalse(ArPoseState.acknowledge(old, 1_040_000_000L))
        val newer = acknowledgment()
        assertTrue(ArPoseState.acknowledge(newer, 1_040_000_000L))
        ArPoseState.requestMarker()
        assertFalse(ArPoseState.acknowledge(newer, 1_050_000_000L))
    }
    @Test fun newSessionAndLossCommandsCannotReusePreviousTrust() {
        pose()
        val old = acknowledgment()
        assertTrue(ArPoseState.acknowledge(old, 1_010_000_000L))
        ArPoseState.alignmentLost(JSONObject(old.toString()).put("generation", "wrong"))
        assertFalse(ArPoseState.markerRequired())
        ArPoseState.alignmentLost(old)
        assertTrue(ArPoseState.markerRequired())
        ArPoseState.beginSession()
        pose(1_030_000_000L)
        assertFalse(ArPoseState.acknowledge(old, 1_040_000_000L))
        assertEquals(1L, ArPoseState.message("connection-2")!!.getLong("seq"))
    }
    @Test fun lockAndDisconnectFenceAutomaticAcquisitions() {
        ArPoseState.setConnected(true)
        pose()
        val old = acknowledgment()
        assertTrue(ArPoseState.acknowledge(old, 1_010_000_000L))
        ArPoseState.setUnlocked(false)
        assertTrue(ArPoseState.markerRequired())
        assertFalse(ArPoseState.acknowledge(old, 1_020_000_000L))
        ArPoseState.setUnlocked(true)
        pose(1_030_000_000L)
        assertTrue(ArPoseState.acknowledge(acknowledgment(), 1_040_000_000L))
        ArPoseState.setConnected(false)
        assertNull(ArPoseState.message("old-connection"))
        assertFalse(ArPoseState.acknowledge(old, 1_050_000_000L))
    }
}
