package com.example.framephone

import android.content.Context
import com.example.framephone.link.PhoneDimensions
import com.example.framephone.link.Protocol
import java.security.MessageDigest

class SettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences("telemetry_v1", Context.MODE_PRIVATE)
    fun dimensions(): PhoneDimensions? = runCatching {
        PhoneDimensions(prefs.getString("width", "")!!.toDouble(),
            prefs.getString("height", "")!!.toDouble())
    }.getOrNull()
    fun save(value: PhoneDimensions) {
        check(prefs.edit().putString("width", value.widthMm.toString())
            .putString("height", value.heightMm.toString()).remove("thickness").commit())
    }
    fun pairedName(): String? = prefs.getString("paired_name", null)
        ?: if (pendingBluetoothCredential() != null) "Steam Frame" else null
    fun remember(name: String, credential: String) {
        check(prefs.edit().putString("paired_name", name)
            .putString("verifier", Protocol.hash(credential.toByteArray(Charsets.UTF_8)))
            .remove("bluetooth_enrollment").commit())
    }
    fun authenticates(credential: String): Boolean {
        if (!credential.matches(Regex("[0-9a-f]{64}"))) return false
        val actual = Protocol.hash(credential.toByteArray(Charsets.US_ASCII)).toByteArray()
        val verifiers = listOfNotNull(prefs.getString("verifier", null), pendingBluetoothCredential()?.let {
            Protocol.hash(it.toByteArray(Charsets.US_ASCII))
        })
        return verifiers.any { MessageDigest.isEqual(it.toByteArray(), actual) }
    }
    fun bluetoothAddress(): String? = prefs.getString("bluetooth_address", null)
    fun hasHeadset() = bluetoothAddress() != null || pairedName() != null
    fun companion(address: String, id: Int) {
        val previous = bluetoothAddress()
        val edit = prefs.edit().putString("bluetooth_address", address.uppercase()).putInt("association_id", id)
        if (previous != null && !previous.equals(address, true)) {
            // A proposal belongs to its selected headset; never reuse a pending
            // credential (or the old peer's verifier) with another companion.
            edit.remove("verifier").remove("paired_name").remove("bluetooth_enrollment")
        }
        check(edit.commit())
    }
    fun connectionEnabled() = prefs.getBoolean("connection_enabled", false)
    fun enableConnection(value: Boolean) { check(prefs.edit().putBoolean("connection_enabled", value).commit()) }
    fun bluetoothVerifier(): String? = pendingBluetoothCredential()?.let {
        Protocol.hash(it.toByteArray(Charsets.US_ASCII))
    } ?: prefs.getString("verifier", null)
    fun pendingBluetoothCredential(): String? = prefs.getString("bluetooth_enrollment", null)
    fun prepareBluetoothEnrollment(replace: Boolean = false) {
        if (pendingBluetoothCredential() != null || (!replace && bluetoothVerifier() != null)) return
        val credential = com.example.framephone.bluetooth.BleProtocol.hex(ByteArray(32).also {
            java.security.SecureRandom().nextBytes(it)
        })
        // Keep the current verifier until Frame acknowledges the new pairing.
        // A lost acknowledgment retries the same pending credential after restart.
        check(prefs.edit().putString("bluetooth_enrollment", credential).commit())
    }
    fun bluetoothEnrollmentAccepted() {
        val credential = pendingBluetoothCredential() ?: return
        check(prefs.edit().putString("paired_name", "Steam Frame")
            .putString("verifier", Protocol.hash(credential.toByteArray(Charsets.US_ASCII)))
            .remove("bluetooth_enrollment").commit())
    }
    fun resetApplicationTrust() {
        check(prefs.edit().remove("paired_name").remove("verifier").remove("bluetooth_enrollment").commit())
    }
    fun forget() {
        check(prefs.edit().remove("paired_name").remove("verifier").remove("bluetooth_enrollment")
            .remove("bluetooth_address").remove("association_id").putBoolean("connection_enabled", false).commit())
    }
}
