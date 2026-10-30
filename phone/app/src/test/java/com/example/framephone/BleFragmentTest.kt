package com.example.framephone

import com.example.framephone.bluetooth.BleProtocol
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

class BleFragmentTest {
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
