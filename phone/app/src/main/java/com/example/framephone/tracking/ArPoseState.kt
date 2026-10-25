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
    @Volatile var status = "ARCore is off"
        private set

    @Synchronized fun beginSession() {
        generation = UUID.randomUUID().toString()
        sequence = 0
        latest = null
        tracking = false
        requestMarker()
        status = "Initializing ARCore — keep the rear camera uncovered"
    }

    @Synchronized fun requestMarker() {
        acquisition = UUID.randomUUID().toString()
        required = true
    }

    @Synchronized fun publish(state: String, translation: FloatArray? = null, quaternion: FloatArray? = null,
                              frameTimestamp: Long = 0, reason: String = "",
                              updatedAtNs: Long = SystemClock.elapsedRealtimeNanos()) {
        val usable = state == "tracking"
        if (tracking && !usable) requestMarker()
        tracking = usable
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
        status = if (!usable) "ARCore $state${if (reason.isEmpty()) "" else ": $reason"}"
            else if (required) "ARCore ready — hold phone and headset still for marker alignment"
            else "ARCore tracking — marker hidden; rear camera must remain uncovered"
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
        status = "ARCore tracking — marker hidden; rear camera must remain uncovered"
        return true
    }

    @Synchronized fun markerRequired() = required

    @Synchronized fun alignmentLost(message: JSONObject) {
        if (!required && message.optString("generation") == generation &&
            message.optString("acquisition") == acquisition) requestMarker()
    }
}
