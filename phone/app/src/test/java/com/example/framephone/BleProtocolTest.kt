package com.example.framephone

import com.example.framephone.bluetooth.BleProtocol
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class BleProtocolTest {
    @Test fun binaryPoseMatchesPythonDecoderContract() {
        val message = JSONObject().put("session", "00000000-0000-0000-0000-000000000001")
            .put("generation", "00000000-0000-0000-0000-000000000002")
            .put("acquisition", "00000000-0000-0000-0000-000000000003")
            .put("seq", 17).put("t_ns", 1_000_000_000L).put("frame_timestamp_ns", 990_000_000L)
            .put("capture_t_ns", 980_000_000L).put("state", "tracking").put("marker_required", true)
            .put("translation_m", JSONArray(listOf(.1,.2,-.6))).put("quaternion_xyzw", JSONArray(listOf(0,0,0,1)))
        val packet = BleProtocol.pose(message, listOf(BleProtocol.Gyro(1_001_000_000L, floatArrayOf(.1f,.2f,.3f))), 244)
        assertEquals("4650425401030001000000000000000000000000000000010000000000000000000000000000000200000000000000000000000000000003110000000000000000ca9a3b000000008033023b00000000009d693a00000000cdcccc3dcdcc4c3e9a9919bf0000000000000000000000000000803f400caa3b00000000cdcccc3dcdcc4c3e9a99993e",BleProtocol.hex(packet))
        assertEquals(BleProtocol.POSE_BYTES, BleProtocol.pose(message, listOf(), 116).size)
    }
    @Test fun controlFragmentsFitTheNegotiatedMtuAndReassemble() {
        val message="a".repeat(600).toByteArray()
        val parts=BleProtocol.fragments(message, 23, 42)
        assertTrue(parts.all { it.size<=20 })
        assertArrayEquals(message, parts.flatMap { it.drop(6) }.toByteArray())
    }
    @Test fun bootstrapProofIsStableAndBoundToTheHeadsetAndRoute() {
        val credential="b".repeat(64)
        val verifier=java.security.MessageDigest.getInstance("SHA-256").digest(credential.toByteArray())
        val text=BleProtocol.bootstrapText("a".repeat(64),"aa:bb:cc:dd:ee:ff","c".repeat(64),"192.168.1.10")
        assertTrue(text.contains("AA:BB:CC:DD:EE:FF"))
        assertEquals("03bfaf65395305bf3b9e69c9387a50df00fb930bed77088d1fe2779e4ec1b750", BleProtocol.proof(verifier,text))
        assertNotEquals(BleProtocol.proof(verifier,text),BleProtocol.proof(verifier,text+"x"))
        assertArrayEquals(verifier,BleProtocol.unhex(BleProtocol.hex(verifier)))
    }
}
