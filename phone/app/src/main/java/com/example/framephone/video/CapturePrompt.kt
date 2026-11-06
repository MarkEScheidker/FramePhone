package com.example.framephone.video

/** One automatic attempt per unlock/context, with recovery from silently blocked launches. */
class CapturePrompt {
    var handled = false
        private set
    private var visible = false
    private var backgroundAttempted = false
    private var foregroundAttempted = false
    private var pendingUntil = 0L

    fun request(nowMs: Long, foreground: Boolean, manual: Boolean = false): Boolean {
        if (visible || nowMs < pendingUntil) return false
        if (!manual && (handled || if (foreground) foregroundAttempted else backgroundAttempted)) return false
        if (foreground) foregroundAttempted = true else backgroundAttempted = true
        pendingUntil = nowMs + 3000
        return true
    }

    fun shown() { handled = true; visible = true; pendingUntil = 0 }
    fun finished() { visible = false }
    fun suppress() { handled = true; pendingUntil = 0 }
    fun unlocked() {
        handled = false
        backgroundAttempted = false
        foregroundAttempted = false
        pendingUntil = 0
    }
}
