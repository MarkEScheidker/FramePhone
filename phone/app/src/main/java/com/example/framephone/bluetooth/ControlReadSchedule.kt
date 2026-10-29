package com.example.framephone.bluetooth

/** Let outgoing tracking work run after each completed GATT control read. */
internal class ControlReadSchedule {
    private var nextRead = 0L
    private var yieldOutgoing = false

    fun reset() { nextRead = 0; yieldOutgoing = false }
    fun shouldRead(now: Long) = now >= nextRead && !yieldOutgoing
    fun mustYield() = yieldOutgoing
    fun outgoingTurn() { yieldOutgoing = false }
    fun completed(now: Long, authenticated: Boolean, standalone: Boolean) {
        nextRead = now + if (authenticated && standalone) 20 else if (authenticated) 500 else 100
        yieldOutgoing = true
    }
}
