package com.example.framephone

import com.example.framephone.bluetooth.BondGate
import com.example.framephone.bluetooth.BondGate.Action.*
import com.example.framephone.bluetooth.BondGate.Bond.*
import org.junit.Assert.*
import org.junit.Test

class BondGateTest {
    @Test fun newBondCompletesBeforeGattIsOpened() {
        val gate = BondGate()
        assertEquals(CREATE_BOND, gate.prepare(NONE))
        repeat(10) { assertEquals(WAIT, gate.prepare(NONE)) }
        gate.changed(BONDING)
        assertEquals(WAIT, gate.prepare(BONDING))
        assertFalse(gate.ready)
        assertEquals(RETRY, gate.changed(BONDED))
        assertEquals(CONNECT, gate.prepare(NONE))
        assertFalse(gate.ready)
        assertEquals(NEGOTIATE, gate.connected(BONDED))
        assertTrue(gate.ready)
        assertEquals(WAIT, gate.prepare(BONDED))
    }
    @Test fun oneSidedUnpairRepairsWithoutReusingThePreviousGattConnection() {
        val gate = BondGate()
        assertEquals(CONNECT, gate.prepare(BONDED))
        gate.connected(BONDED)
        assertEquals(BLOCK, gate.changed(NONE))
        gate.disconnected()
        gate.retry()
        assertEquals(CREATE_BOND, gate.prepare(NONE))
        gate.changed(BONDING)
        assertEquals(RETRY, gate.changed(BONDED))
        assertEquals(CONNECT, gate.prepare(BONDED))
        assertEquals(NEGOTIATE, gate.connected(BONDED))
        gate.disconnected()
        assertEquals(CONNECT, gate.prepare(BONDED))
    }
    @Test fun preflightJoinsAnExistingBondAndHonorsCancellation() {
        val gate = BondGate()
        assertEquals(WAIT, gate.prepare(BONDING))
        assertTrue(gate.waiting)
        assertEquals(BLOCK, gate.changed(NONE))
        repeat(10) { assertEquals(BLOCK, gate.prepare(NONE)) }
        gate.retry()
        assertEquals(CREATE_BOND, gate.prepare(NONE))
    }

    @Test fun setupWaitsForBondCompletionAndIgnoresDuplicates() {
        val gate = BondGate()
        assertEquals(CREATE_BOND, gate.connected(NONE))
        assertEquals(WAIT, gate.changed(BONDING))
        assertEquals(NEGOTIATE, gate.changed(BONDED))
        assertEquals(WAIT, gate.changed(BONDED)) // a duplicate cannot restart GATT setup
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
        assertEquals(BLOCK, gate.changed(NONE))
        gate.retry()
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
    @Test fun connectionDropDoesNotStartASecondBondWhileConfirmationIsPending() {
        val gate = BondGate()
        assertEquals(CREATE_BOND, gate.connected(NONE))
        gate.changed(BONDING)
        gate.disconnected()
        assertTrue(gate.waiting)
        assertFalse(gate.ready)
        assertEquals(WAIT, gate.connected(NONE))
        gate.disconnected()
        assertEquals(RETRY, gate.changed(BONDED))
        assertEquals(NEGOTIATE, gate.connected(NONE)) // lagging getter, confirmed bond retained
        assertTrue(gate.ready)
    }
    @Test fun duplicateConnectionCallbacksCannotRenegotiateOrCreateAnotherBond() {
        val gate = BondGate()
        assertEquals(CREATE_BOND, gate.connected(NONE))
        assertEquals(WAIT, gate.connected(NONE))
        assertEquals(NEGOTIATE, gate.changed(BONDED))
        assertEquals(WAIT, gate.connected(BONDED))
        assertEquals(WAIT, gate.changed(BONDED))
        assertTrue(gate.ready)
    }
    @Test fun retryAfterGattFailureKeepsTheBondInsteadOfRequestingNewNumbers() {
        val gate = BondGate()
        gate.connected(NONE)
        gate.changed(BONDED)
        gate.reject()
        gate.disconnected()
        gate.retry()
        assertEquals(NEGOTIATE, gate.connected(NONE))
        assertFalse(gate.waiting)
        assertEquals(BLOCK, gate.changed(NONE)) // only an explicit unpair discards it
    }
    @Test fun bondCompletionBeforeConnectionCallbackStillInitializesExactlyOnce() {
        val gate = BondGate()
        assertEquals(RETRY, gate.changed(BONDED))
        assertEquals(NEGOTIATE, gate.connected(NONE))
        assertEquals(WAIT, gate.changed(BONDED))
        gate.disconnected()
        assertFalse(gate.ready)
        assertEquals(NEGOTIATE, gate.connected(BONDED))
    }
    @Test fun duplicateBondCompletionCannotRestartARejectedAttempt() {
        val gate = BondGate()
        gate.connected(BONDED)
        gate.reject()
        gate.disconnected()
        assertEquals(WAIT, gate.changed(BONDED))
        assertTrue(gate.blocked)
        gate.retry()
        assertEquals(NEGOTIATE, gate.connected(BONDED))
    }
    @Test fun securityErrorsStopButTransportErrorsCanRetry() {
        for (status in listOf(5, 8, 12, 15, 137)) assertTrue(BondGate.securityFailure(status))
        for (status in listOf(0, 13, 133, 147, 257)) assertFalse(BondGate.securityFailure(status))
    }
}
