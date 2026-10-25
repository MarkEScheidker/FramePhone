package com.example.framephone.tracking

/** Bounds each automatic acquisition; timeout never acknowledges or restores an alignment. */
class MarkerVisibility(private val timeoutMs: Long = 20_000) {
    private var acquisition: String? = null
    private var startedAt: Long? = null
    var timedOut = false
        private set

    fun update(id: String, enabled: Boolean, required: Boolean, nowMs: Long): Boolean {
        if (id != acquisition) {
            acquisition = id
            startedAt = null
            timedOut = false
        }
        if (!required) { timedOut = false; startedAt = null; return false }
        if (!enabled) return false
        val start = startedAt ?: nowMs.also { startedAt = it }
        timedOut = nowMs - start >= timeoutMs
        return !timedOut
    }
}
