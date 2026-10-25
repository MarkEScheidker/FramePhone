package com.example.framephone.tracking

import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Latest-only pose mailbox. Session/anchor and acquisition IDs fence delayed acknowledgments. */
object ArPoseState {
    private var generation = UUID.randomUUID().toString()
    private var acquisition = UUID.randomUUID().toString()
    private var sequence = 0L
    private var required = true
    private var tracking = false
    private var latest: String? = null
    @Volatile var status = "Ready"
        private set
    @Volatile var detail = ""
        private set
    @Volatile var connected = false
        private set
    @Volatile var unlocked = true
        private set
    @Volatile var running = false
        internal set
    @Volatile var overlayTimedOut = false
        internal set
    @Volatile var failed = false
        private set

    @Synchronized fun setConnected(value: Boolean) {
        if (connected == value) return
        connected = value
        tracking = false
        latest = null
        requestMarker()
        status = if (value) "Starting tracking" else "Waiting for headset"
    }

    @Synchronized fun setUnlocked(value: Boolean) {
        if (unlocked && !value) requestMarker()
        unlocked = value
    }

    @Synchronized fun acquisitionId() = acquisition

    @Synchronized fun beginSession() {
        generation = UUID.randomUUID().toString()
        sequence = 0
        latest = null
        tracking = false
        failed = false
        detail = ""
        requestMarker()
        status = if (connected) "Starting tracking" else "Waiting for headset"
    }

    @Synchronized fun requestMarker() {
        acquisition = UUID.randomUUID().toString()
        required = true
        overlayTimedOut = false
    }

    @Synchronized fun publish(state: String, translation: FloatArray? = null, quaternion: FloatArray? = null,
                              frameTimestamp: Long = 0, reason: String = "",
                              updatedAtNs: Long = SystemClock.elapsedRealtimeNanos()) {
        val usable = state == "tracking"
        if (tracking && !usable) requestMarker()
        tracking = usable
        failed = state == "error"
        detail = reason.take(120)
        val message = JSONObject().put("type", "arcore_pose").put("generation", generation)
            .put("acquisition", acquisition).put("seq", ++sequence)
            // Frame.timestamp has an unspecified epoch. This is explicitly update time,
            // not a claim that the camera exposure clock equals elapsedRealtime.
            .put("t_ns", updatedAtNs).put("frame_timestamp_ns", frameTimestamp)
            .put("state", state).put("reason", reason.take(120)).put("marker_required", required)
            .put("transform", "T_AD").put("time_source", "update_elapsed_realtime_ns")
        if (usable) {
            require(translation?.size == 3 && quaternion?.size == 4)
            message.put("translation_m", JSONArray(translation!!.map { it.toDouble() }))
                .put("quaternion_xyzw", JSONArray(quaternion!!.map { it.toDouble() }))
        }
        latest = message.toString()
        status = when {
            failed -> "Tracking unavailable"
            !connected -> "Waiting for headset"
            state == "stopped" -> "Tracking stopped"
            !usable -> when (reason) {
                "INSUFFICIENT_LIGHT" -> "More light needed"
                "INSUFFICIENT_FEATURES" -> "Point the rear camera at the room"
                "EXCESSIVE_MOTION" -> "Hold still"
                "camera_in_use" -> "Camera in use"
                "screen_locked" -> "Phone locked"
                else -> "Starting tracking"
            }
            required -> "Hold still"
            else -> "Tracking"
        }
    }

    @Synchronized fun message(session: String): JSONObject? = latest?.let {
        JSONObject(it).put("session", session).put("marker_required", required)
    }

    @Synchronized fun acknowledge(message: JSONObject, nowNs: Long = SystemClock.elapsedRealtimeNanos()): Boolean {
        if (!tracking || !required || message.optString("generation") != generation ||
            message.optString("acquisition") != acquisition) return false
        val sample = latest?.let { JSONObject(it) } ?: return false
        if (sample.getString("generation") != generation || sample.getString("acquisition") != acquisition ||
            nowNs - sample.getLong("t_ns") !in 0..250_000_000L) return false
        required = false
        overlayTimedOut = false
        status = "Tracking"
        return true
    }

    @Synchronized fun markerRequired() = required

    @Synchronized fun alignmentLost(message: JSONObject) {
        if (!required && message.optString("generation") == generation &&
            message.optString("acquisition") == acquisition) requestMarker()
    }
}
