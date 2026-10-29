package com.example.framephone.link

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.util.ArrayDeque
import com.example.framephone.bluetooth.BluetoothPose

/** Callback copies only. Network writes never run on the sensor thread. */
class SensorFeed(context: Context) : SensorEventListener {
    private val manager = context.getSystemService(SensorManager::class.java)
    private val worker = HandlerThread("phone-sensors").apply { start() }
    private val queue = ArrayDeque<JSONObject>()
    private val sequences = mutableMapOf<Int, Long>()
    private val names = java.util.concurrent.ConcurrentHashMap<Int, String>()
    private var dropped = 0L
    val capabilities = JSONArray()

    init {
        val choices = listOf(
            Triple("gyro", Sensor.TYPE_GYROSCOPE_UNCALIBRATED, Sensor.TYPE_GYROSCOPE),
            Triple("accel", Sensor.TYPE_ACCELEROMETER_UNCALIBRATED, Sensor.TYPE_ACCELEROMETER),
            Triple("mag", Sensor.TYPE_MAGNETIC_FIELD_UNCALIBRATED, Sensor.TYPE_MAGNETIC_FIELD))
        choices.forEach { (name, raw, calibrated) ->
            val sensor = manager.getDefaultSensor(raw) ?: manager.getDefaultSensor(calibrated)
            val capability = JSONObject().put("sensor", name).put("available", false)
            if (sensor != null) {
                names[sensor.type] = name
                val period = if (name == "mag") 20000 else 5000
                val registered = manager.registerListener(this, sensor, period, 0, Handler(worker.looper))
                capability.put("available", registered).put("android_type", sensor.type)
                    .put("uncalibrated", sensor.type == raw).put("requested_hz", 1000000 / period)
                    .put("min_delay_us", sensor.minDelay).put("name", sensor.name)
                    .put("units", when (name) { "gyro" -> "rad/s"; "accel" -> "m/s^2"; else -> "uT" })
            }
            capabilities.put(capability)
        }
    }

    override fun onSensorChanged(event: SensorEvent) {
        val name = names[event.sensor.type] ?: return
        if (name == "gyro" && event.values.size >= 3) {
            val raw = event.sensor.type == Sensor.TYPE_GYROSCOPE_UNCALIBRATED
            if (!raw || event.values.size >= 6) BluetoothPose.gyro(event.timestamp,
                FloatArray(3) { event.values[it] - if (raw) event.values[it+3] else 0f })
        }
        synchronized(queue) {
            val sequence = (sequences[event.sensor.type] ?: 0L) + 1
            sequences[event.sensor.type] = sequence
            val sample = JSONObject().put("sensor", name).put("seq", sequence)
                .put("t_ns", event.timestamp).put("accuracy", event.accuracy)
                .put("v", JSONArray(event.values.take(3)))
            if (event.values.size >= 6) sample.put("bias", JSONArray(event.values.slice(3..5)))
            if (queue.size >= 256) { queue.removeFirst(); dropped++ }
            queue.addLast(sample)
        }
    }
    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    fun batch(session: String): JSONObject = synchronized(queue) {
        val cutoff = SystemClock.elapsedRealtimeNanos() - 100000000L
        while (queue.isNotEmpty() && queue.first.getLong("t_ns") < cutoff) { queue.removeFirst(); dropped++ }
        val samples = JSONArray()
        repeat(minOf(64, queue.size)) { samples.put(queue.removeFirst()) }
        JSONObject().put("type", "samples").put("session", session)
            .put("dropped", dropped).put("samples", samples)
    }
    fun latestBatch(session: String): JSONObject = synchronized(queue) {
        val latest = mutableMapOf<String, JSONObject>()
        while (queue.isNotEmpty()) {
            val sample = queue.removeFirst()
            latest[sample.getString("sensor")] = sample
        }
        JSONObject().put("type", "samples").put("session", session)
            .put("dropped", dropped).put("samples", JSONArray(latest.values.toList()))
    }
    fun close() {
        manager.unregisterListener(this)
        worker.quitSafely()
    }
}
