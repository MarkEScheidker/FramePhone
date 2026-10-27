package com.example.framephone.bluetooth

/** Bond completion fences GATT setup; security failures stop automatic retries. */
internal class BondGate {
    enum class Bond { NONE, BONDING, BONDED }
    enum class Action { WAIT, CREATE_BOND, NEGOTIATE, RETRY, BLOCK }
    var blocked = false
        private set
    private var waiting = false
    private var lastBond = Bond.NONE

    fun connected(bond: Bond): Action {
        if (blocked) return Action.BLOCK
        lastBond = bond
        waiting = bond != Bond.BONDED
        return when (bond) {
            Bond.NONE -> Action.CREATE_BOND
            Bond.BONDING -> Action.WAIT
            Bond.BONDED -> Action.NEGOTIATE
        }
    }
    fun changed(bond: Bond): Action {
        val previous = lastBond
        lastBond = bond
        return when {
            bond == Bond.NONE && waiting -> { reject(); Action.BLOCK }
            bond == Bond.BONDED && waiting -> { waiting = false; blocked = false; Action.NEGOTIATE }
            bond == Bond.NONE && previous == Bond.BONDED && !blocked -> { reject(); Action.BLOCK }
            bond == Bond.BONDED || (bond == Bond.NONE && blocked && previous == Bond.BONDED) -> {
                blocked = false; Action.RETRY
            }
            else -> Action.WAIT
        }
    }
    fun retry() { blocked = false; waiting = false }
    fun reject() { blocked = true; waiting = false }
    fun disconnected() { waiting = false }

    companion object {
        // ATT authentication/authorization/key-size/encryption and Android's
        // internal GATT_AUTH_FAIL (0x89). Transport errors such as133 may retry.
        fun securityFailure(status: Int) = status in setOf(5, 8, 12, 15, 137)
    }
}
