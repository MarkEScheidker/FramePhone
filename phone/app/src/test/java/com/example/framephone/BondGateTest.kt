package com.example.framephone

import com.example.framephone.bluetooth.BondGate
import com.example.framephone.bluetooth.BondGate.Action.*
import com.example.framephone.bluetooth.BondGate.Bond.*
import org.junit.Assert.*
import org.junit.Test

class BondGateTest {
    @Test fun setupWaitsForBondCompletionAndIgnoresDuplicates() {
        val gate = BondGate()
        assertEquals(CREATE_BOND, gate.connected(NONE))
        assertEquals(WAIT, gate.changed(BONDING))
        assertEquals(NEGOTIATE, gate.changed(BONDED))
        assertEquals(RETRY, gate.changed(BONDED)) // only reconnect when disconnected
    }
    @Test fun alreadyBondedReconnectDoesNotAskToPairAgain() {
        assertEquals(NEGOTIATE, BondGate().connected(BONDED))
        assertEquals(WAIT, BondGate().connected(BONDING))
    }
    @Test fun rejectedBondDoesNotBecomeAConnectionLoop() {
        val gate = BondGate()
        gate.connected(NONE)
        gate.changed(BONDING)
        assertEquals(BLOCK, gate.changed(NONE))
        gate.disconnected()
        assertEquals(WAIT, gate.changed(NONE)) // duplicate failure broadcast stays blocked
        repeat(10) { assertEquals(BLOCK, gate.connected(NONE)) }
        assertTrue(gate.blocked)
    }
    @Test fun removingARejectedSavedBondAllowsExplicitRepair() {
        val gate = BondGate()
        gate.connected(BONDED)
        gate.reject() // GATT_AUTH_FAIL137 after an old Just Works bond
        gate.disconnected()
        assertEquals(BLOCK, gate.connected(BONDED))
        assertEquals(RETRY, gate.changed(NONE))
        assertEquals(CREATE_BOND, gate.connected(NONE))
        assertEquals(NEGOTIATE, gate.changed(BONDED))
    }
    @Test fun manualUnpairPausesTheCompanionUntilExplicitRepair() {
        val gate = BondGate()
        gate.connected(BONDED)
        assertEquals(BLOCK, gate.changed(NONE))
        gate.disconnected()
        assertEquals(BLOCK, gate.connected(NONE))
        gate.retry()
        assertEquals(CREATE_BOND, gate.connected(NONE))
    }
    @Test fun securityErrorsStopButTransportErrorsCanRetry() {
        for (status in listOf(5, 8, 12, 15, 137)) assertTrue(BondGate.securityFailure(status))
        for (status in listOf(0, 13, 133, 147, 257)) assertFalse(BondGate.securityFailure(status))
    }
}
