package com.example.framephone

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

/** Exercise Android's actual preferences without touching the user's pairing. */
@RunWith(AndroidJUnit4::class)
class PairingRecoveryTest {
    private fun isolated(check: (Context) -> Unit) {
        val target = InstrumentationRegistry.getInstrumentation().targetContext
        val name = "pairing-test-${UUID.randomUUID()}"
        val context = object : ContextWrapper(target) {
            override fun getSharedPreferences(ignored: String?, mode: Int): SharedPreferences =
                target.getSharedPreferences(name, mode)
        }
        try { check(context) } finally { target.deleteSharedPreferences(name) }
    }
    @Test fun interruptedEnrollmentRetainsTheSamePendingCredential() = isolated { context ->
        val store = SettingsStore(context)
        store.prepareBluetoothEnrollment()
        val pending = store.pendingBluetoothCredential()!!
        val restored = SettingsStore(context)
        restored.prepareBluetoothEnrollment(replace = true)
        assertEquals(pending, restored.pendingBluetoothCredential())
        restored.bluetoothEnrollmentAccepted()
        assertNull(restored.pendingBluetoothCredential())
        assertTrue(SettingsStore(context).authenticates(pending))
    }
    @Test fun replacementDoesNotDiscardWorkingVerifierBeforeAcknowledgment() = isolated { context ->
        val store = SettingsStore(context)
        val old = "b".repeat(64)
        store.remember("Steam Frame", old)
        store.prepareBluetoothEnrollment(replace = true)
        val pending = store.pendingBluetoothCredential()!!
        assertTrue(store.authenticates(old))
        assertTrue(store.authenticates(pending)) // permits TLS/ready-ACK ordering
        store.bluetoothEnrollmentAccepted()
        assertFalse(store.authenticates(old))
        assertTrue(store.authenticates(pending))
    }
    @Test fun identityUpgradeKeepsTheApprovedCompanionForAppTrustRecovery() = isolated { context ->
        val store = SettingsStore(context)
        store.companion("AA:BB:CC:DD:EE:FF", 7)
        store.enableConnection(true)
        store.remember("Steam Frame", "b".repeat(64))
        store.resetApplicationTrust()
        assertEquals("AA:BB:CC:DD:EE:FF", store.bluetoothAddress())
        assertTrue(store.connectionEnabled())
        assertNull(store.bluetoothVerifier())
    }
    @Test fun changingCompanionsNeverReusesTheOldPeersCredential() = isolated { context ->
        val store = SettingsStore(context)
        store.companion("AA:BB:CC:DD:EE:FF", 7)
        store.remember("Steam Frame", "b".repeat(64))
        store.prepareBluetoothEnrollment(replace = true)
        val pending = store.pendingBluetoothCredential()!!
        store.companion("11:22:33:44:55:66", 8)
        assertNull(store.pendingBluetoothCredential())
        assertNull(store.bluetoothVerifier())
        assertFalse(store.authenticates("b".repeat(64)))
        assertFalse(store.authenticates(pending))
    }
    @Test fun forgetRemovesPendingTrustAndStopsAutomaticWake() = isolated { context ->
        val store = SettingsStore(context)
        store.prepareBluetoothEnrollment()
        val pending = store.pendingBluetoothCredential()!!
        store.companion("AA:BB:CC:DD:EE:FF", 7)
        store.enableConnection(true)
        store.forget()
        assertNull(store.pendingBluetoothCredential())
        assertNull(store.bluetoothVerifier())
        assertNull(store.bluetoothAddress())
        assertFalse(store.connectionEnabled())
        assertFalse(store.authenticates(pending))
    }
}
