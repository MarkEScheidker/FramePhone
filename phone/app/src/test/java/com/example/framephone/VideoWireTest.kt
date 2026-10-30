package com.example.framephone

import com.example.framephone.video.VideoWire
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream

class VideoWireTest {
    @Test fun packetFramingAndPreciseTimestamp() {
        val output=ByteArrayOutputStream()
        VideoWire.write(DataOutputStream(output),byteArrayOf(0,0,0,1,0x65),VideoWire.KEYFRAME,9_007_199_254_740_993)
        val input=DataInputStream(output.toByteArray().inputStream())
        assertEquals(5,input.readInt()); assertEquals(2,input.readInt()); assertEquals(9_007_199_254_740_993,input.readLong())
        assertEquals(0,input.readUnsignedByte())
    }
    @Test fun normalizesMultipleLengthPrefixedNalsAndRejectsTruncation() {
        val source=byteArrayOf(0,0,0,2,0x67,1,0,0,0,1,0x68)
        assertArrayEquals(byteArrayOf(0,0,0,1,0x67,1,0,0,0,1,0x68),VideoWire.annexB(source))
        assertThrows(IllegalArgumentException::class.java) {VideoWire.annexB(byteArrayOf(0,0,0,10,0x65))}
        assertThrows(IllegalArgumentException::class.java) {VideoWire.write(DataOutputStream(ByteArrayOutputStream()),ByteArray(0),0,0)}
        assertThrows(IllegalArgumentException::class.java) {VideoWire.annexB(ByteArray(VideoWire.MAX_PACKET+1))}
    }
}
