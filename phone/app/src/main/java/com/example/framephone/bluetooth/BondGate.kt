package com.example.framephone.bluetooth

/** Bond lifetime is independent of the GATT connection carrying setup traffic. */
internal class BondGate {
    enum class Bond { NONE, BONDING, BONDED }
    enum class Action { WAIT, CREATE_BOND, CONNECT, NEGOTIATE, RETRY, BLOCK }
    var blocked = false
        private set
    var waiting = false
        private set
    var ready = false
        private set
    private var connected = false
    private var lastBond = Bond.NONE

    /** Finish key exchange before opening a GATT connection with those keys. */
    fun prepare(bond: Bond): Action {
        if (blocked) return Action.BLOCK
        if (waiting || connected) return Action.WAIT
        if (lastBond != Bond.BONDED) lastBond = bond
        waiting = lastBond != Bond.BONDED
        return when (lastBond) {
            Bond.NONE -> Action.CREATE_BOND
            Bond.BONDING -> Action.WAIT
            Bond.BONDED -> Action.CONNECT
        }
    }

    fun connected(bond: Bond): Action {
        if (blocked) return Action.BLOCK
        if (connected) return Action.WAIT
        connected = true
        if (waiting) return Action.WAIT
        // A cached getter may lag the BONDED broadcast. Only an actual unpair
        // event may discard a bond already observed by this client.
        if (lastBond != Bond.BONDED) lastBond = bond
        waiting = lastBond != Bond.BONDED
        ready = !waiting
        return when (lastBond) {
            Bond.NONE -> Action.CREATE_BOND
            Bond.BONDING -> Action.WAIT
            Bond.BONDED -> Action.NEGOTIATE
        }
    }
    fun changed(bond: Bond): Action {
        val previous = lastBond
        lastBond = bond
        return when {
            bond == Bond.NONE && (waiting || previous == Bond.BONDED) -> { reject(); Action.BLOCK }
            bond == Bond.BONDING -> { waiting = true; ready = false; Action.WAIT }
            bond == Bond.BONDED -> {
                if (blocked && !waiting) return Action.WAIT
                val initialize = waiting || !ready
                waiting = false; blocked = false; ready = connected
                if (!connected) Action.RETRY else if (initialize) Action.NEGOTIATE else Action.WAIT
            }
            else -> Action.WAIT
        }
    }
    fun reject() { blocked = true; waiting = false; ready = false }
    fun disconnected() { connected = false; ready = false } // Bonding may still be in progress.

    companion object {
        fun securityFailure(status: Int) = status in setOf(5, 8, 12, 15, 137)
    }
}
