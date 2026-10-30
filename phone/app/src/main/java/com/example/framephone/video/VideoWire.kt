package com.example.framephone.video

import java.io.DataOutputStream

/** Annex-B H.264 access units. TLS supplies integrity and confidentiality. */
object VideoWire {
    const val PORT = 47644
    const val MAX_PACKET = 2 * 1024 * 1024
    const val CONFIG = 1
    const val KEYFRAME = 2
    const val HEARTBEAT = 4
    fun annexB(bytes: ByteArray): ByteArray {
        require(bytes.isNotEmpty() && bytes.size <= MAX_PACKET)
        if (bytes.size >= 4 && bytes[0] == 0.toByte() && bytes[1] == 0.toByte() &&
            (bytes[2] == 1.toByte() || (bytes[2] == 0.toByte() && bytes[3] == 1.toByte()))) return bytes
        val result = java.io.ByteArrayOutputStream()
        var cursor = 0
        while (cursor < bytes.size) {
            require(cursor + 4 <= bytes.size)
            val size = java.nio.ByteBuffer.wrap(bytes, cursor, 4).int
            cursor += 4
            require(size > 0 && size <= bytes.size - cursor)
            result.write(byteArrayOf(0, 0, 0, 1)); result.write(bytes, cursor, size)
            cursor += size
        }
        return result.toByteArray().also { require(it.size <= MAX_PACKET) }
    }
    fun write(output: DataOutputStream, bytes: ByteArray, flags: Int, ptsUs: Long) {
        require(bytes.size <= MAX_PACKET && ptsUs >= 0 && flags in 0..7)
        require(bytes.isNotEmpty() || flags == HEARTBEAT)
        output.writeInt(bytes.size); output.writeInt(flags); output.writeLong(ptsUs)
        output.write(bytes); output.flush()
    }
}
