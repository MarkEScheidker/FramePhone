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
    fun remember(name: String, credential: String) {
        check(prefs.edit().putString("paired_name", name)
            .putString("verifier", Protocol.hash(credential.toByteArray(Charsets.UTF_8)))
            .remove("bluetooth_enrollment").commit())
    }
    fun authenticates(credential: String): Boolean {
        val expected = prefs.getString("verifier", null) ?: return false
        return credential.matches(Regex("[0-9a-f]{64}")) && MessageDigest.isEqual(
            expected.toByteArray(), Protocol.hash(credential.toByteArray(Charsets.UTF_8)).toByteArray())
    }
    fun bluetoothAddress(): String? = prefs.getString("bluetooth_address", null)
    fun companion(address: String, id: Int) {
        check(prefs.edit().putString("bluetooth_address", address.uppercase()).putInt("association_id", id).commit())
    }
    fun connectionEnabled() = prefs.getBoolean("connection_enabled", false)
    fun enableConnection(value: Boolean) { check(prefs.edit().putBoolean("connection_enabled", value).commit()) }
    fun bluetoothVerifier(): String? = prefs.getString("verifier", null)
    fun pendingBluetoothCredential(): String? = prefs.getString("bluetooth_enrollment", null)
    fun prepareBluetoothEnrollment() {
        if (bluetoothVerifier() != null) return
        val credential = com.example.framephone.bluetooth.BleProtocol.hex(ByteArray(32).also {
            java.security.SecureRandom().nextBytes(it)
        })
        check(prefs.edit().putString("paired_name", "Steam Frame")
            .putString("verifier", Protocol.hash(credential.toByteArray(Charsets.US_ASCII)))
            .putString("bluetooth_enrollment", credential).commit())
    }
    fun bluetoothEnrollmentAccepted() { check(prefs.edit().remove("bluetooth_enrollment").commit()) }
    fun forget() {
        check(prefs.edit().remove("paired_name").remove("verifier").remove("bluetooth_enrollment")
            .remove("bluetooth_address").remove("association_id").putBoolean("connection_enabled", false).commit())
    }
}
