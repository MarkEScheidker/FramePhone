package com.example.framephone

import com.example.framephone.bluetooth.BleProtocol
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

class BleFragmentTest {
    @Test fun gyroPacketsPreserveIdentityAndLatestSamples() {
        val id = "00000000-0000-0000-0000-000000000001"
        val message = JSONObject().put("session", id).put("generation", id).put("acquisition", id)
        val samples = (1..4).map { BleProtocol.Gyro(it.toLong(), floatArrayOf(.1f, .2f, .3f)) }
        val packet = BleProtocol.gyro(message, samples, 94)
        val buffer = ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN)
        val magic = ByteArray(4); buffer.get(magic)
        assertArrayEquals("FPIM".toByteArray(Charsets.US_ASCII), magic)
        assertEquals(1, buffer.get().toInt())
        repeat(3) {
            val uuid = ByteArray(16); buffer.get(uuid)
            assertEquals(1, uuid.last().toInt())
            assertTrue(uuid.dropLast(1).all { it == 0.toByte() })
        }
        assertEquals(2, buffer.get().toInt())
        assertEquals(3L, buffer.long)
        repeat(3) { buffer.float }
        assertEquals(4L, buffer.long)
        repeat(3) { buffer.float }
        assertEquals(0, buffer.remaining())
    }

    @Test fun fragmentsFitAttAndAndroidAttributeLimits() {
        val message = ByteArray(32768) { it.toByte() }
        for (mtu in listOf(23, 247, 512, 515, 516, 517)) {
            val restored = ByteArrayOutputStream()
            val fragments = BleProtocol.fragments(message, mtu, 0x9abc)
            for (fragment in fragments) {
                assertTrue("MTU $mtu produced ${fragment.size} bytes", fragment.size <= minOf(mtu - 3, 512))
                val buffer = ByteBuffer.wrap(fragment).order(ByteOrder.LITTLE_ENDIAN)
                assertEquals(0x9abc, buffer.short.toInt() and 0xffff)
                assertEquals(restored.size(), buffer.short.toInt() and 0xffff)
                assertEquals(message.size, buffer.short.toInt() and 0xffff)
                val payload = ByteArray(buffer.remaining())
                buffer.get(payload)
                restored.write(payload)
            }
            assertArrayEquals(message, restored.toByteArray())
        }
    }
}
