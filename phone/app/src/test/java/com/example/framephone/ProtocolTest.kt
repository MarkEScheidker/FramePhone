package com.example.framephone

import com.example.framephone.link.PhoneDimensions
import com.example.framephone.link.Protocol
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream

class ProtocolTest {
    @Test fun measuredBodyDimensionsUseMetersAndRejectInvalidInput() {
        val json = PhoneDimensions(75.0, 160.0).json()
        assertEquals(0.075, json.getDouble("width_m"), 1e-9)
        assertEquals("body_or_case", json.getString("boundary"))
        for (bad in listOf(Double.NaN, Double.POSITIVE_INFINITY, -1.0, 0.0, 501.0)) {
            assertThrows(IllegalArgumentException::class.java) { PhoneDimensions(bad, 160.0) }
        }
        assertThrows(IllegalArgumentException::class.java) { PhoneDimensions(75.0, 60.0) }
        assertFalse(json.has("thickness_m"))
    }
    @Test fun wireRetainsIntegerNanosecondsAndUsesBigEndianLength() {
        val bytes = ByteArrayOutputStream()
        Protocol.write(DataOutputStream(bytes), JSONObject().put("t_ns", 9007199254740993L).put("type", "sample"))
        val data = bytes.toByteArray()
        assertEquals(data.size - 4, DataInputStream(ByteArrayInputStream(data)).readInt())
        assertEquals(9007199254740993L, Protocol.read(DataInputStream(ByteArrayInputStream(data))).getLong("t_ns"))
    }
    @Test fun oversizedAndDeepMessagesFailBeforeJsonParsing() {
        val bytes = ByteArrayOutputStream()
        DataOutputStream(bytes).writeInt(65537)
        assertThrows(IllegalArgumentException::class.java) { Protocol.read(DataInputStream(ByteArrayInputStream(bytes.toByteArray()))) }
        bytes.reset()
        val text = "[".repeat(12) + "0" + "]".repeat(12)
        DataOutputStream(bytes).apply { writeInt(text.length); writeBytes(text) }
        assertThrows(IllegalArgumentException::class.java) { Protocol.read(DataInputStream(ByteArrayInputStream(bytes.toByteArray()))) }
    }
    @Test fun certificateFingerprintHasKnownCrossLanguageEncoding() {
        assertEquals("BA78 16BF 8F01 CFEA", Protocol.fingerprint(Protocol.hash("abc".toByteArray())))
        assertEquals("B20D D8BD D812 E185", Protocol.pairingFingerprint("a".repeat(64), "b".repeat(64), "c".repeat(64)))
        assertNotEquals(Protocol.pairingFingerprint("a".repeat(64), "b".repeat(64), "c".repeat(64)),
            Protocol.pairingFingerprint("a".repeat(64), "d".repeat(64), "c".repeat(64)))
        assertThrows(IllegalArgumentException::class.java) { Protocol.pairingFingerprint("a", "b", "c") }
    }
}
