package com.example.framephone.bluetooth

import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object BleProtocol {
    val SERVICE: UUID = UUID.fromString("f7a10001-81a6-4c44-9c79-99ac54174901")
    val CONTROL: UUID = UUID.fromString("f7a10002-81a6-4c44-9c79-99ac54174901")
    val POSE: UUID = UUID.fromString("f7a10003-81a6-4c44-9c79-99ac54174901")
    const val POSE_BYTES = 116
    data class Gyro(val time: Long, val value: FloatArray)
    fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it.toInt() and 255) }
    fun unhex(text: String): ByteArray {
        require(text.matches(Regex("[0-9a-f]{64}")))
        return text.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    }
    fun proof(key: ByteArray, text: String): String = hex(Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(key, "HmacSHA256")); doFinal(text.toByteArray(Charsets.US_ASCII))
    })
    fun bootstrapText(challenge: String, address: String, pin: String, host: String) =
        "framephone-bt-bootstrap-v1\n$challenge\n${address.uppercase()}\n$pin\n$host\n47643\n"

    fun fragments(message: ByteArray, mtu: Int, id: Int): List<ByteArray> {
        require(message.size in 1..1024 && mtu >= 23)
        val size = mtu-9
        return message.toList().chunked(size).mapIndexed { index, part ->
            ByteBuffer.allocate(6+part.size).order(ByteOrder.LITTLE_ENDIAN)
                .putShort(id.toShort()).putShort((index*size).toShort()).putShort(message.size.toShort())
                .put(part.toByteArray()).array()
        }
    }
    private fun uuid(value: String): ByteArray {
        val id = UUID.fromString(value)
        return ByteBuffer.allocate(16).putLong(id.mostSignificantBits).putLong(id.leastSignificantBits).array()
    }
    fun pose(message: JSONObject, samples: List<Gyro>, maximumBytes: Int): ByteArray {
        require(maximumBytes >= POSE_BYTES)
        val states = listOf("tracking", "paused", "error", "stopped")
        val state = states.indexOf(message.getString("state"))
        require(state >= 0)
        val tracked = state == 0
        val capture = if (tracked && message.has("capture_t_ns")) message.getLong("capture_t_ns") else 0L
        val stamp = message.getLong("t_ns")
        val gyro = samples.filter { it.time-stamp in -200_000_000L..250_000_000L }
            .takeLast(minOf(19, (maximumBytes-POSE_BYTES)/20))
        val packet = ByteBuffer.allocate(POSE_BYTES+20*gyro.size).order(ByteOrder.LITTLE_ENDIAN)
        packet.put("FPBT".toByteArray(Charsets.US_ASCII)).put(1.toByte())
        packet.put(((if (message.getBoolean("marker_required")) 1 else 0) or (if (capture>0) 2 else 0)).toByte())
        val reasons = listOf("", "headset_not_worn", "user_dismissed", "screen_locked", "camera_in_use")
        val reason = reasons.indexOf(message.optString("reason")).coerceAtLeast(0)
        packet.put((state or (reason shl 4)).toByte()).put(gyro.size.toByte())
        packet.put(uuid(message.getString("session"))).put(uuid(message.getString("generation")))
            .put(uuid(message.getString("acquisition"))).putLong(message.getLong("seq"))
            .putLong(stamp).putLong(message.getLong("frame_timestamp_ns")).putLong(capture)
        val p = if (tracked) message.getJSONArray("translation_m") else null
        val q = if (tracked) message.getJSONArray("quaternion_xyzw") else null
        repeat(3) { packet.putFloat(p?.getDouble(it)?.toFloat() ?: 0f) }
        repeat(4) { packet.putFloat(q?.getDouble(it)?.toFloat() ?: if (it==3) 1f else 0f) }
        gyro.forEach { sample -> packet.putLong(sample.time); sample.value.forEach { packet.putFloat(it) } }
        return packet.array()
    }
}
