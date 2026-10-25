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
            .putString("verifier", Protocol.hash(credential.toByteArray(Charsets.UTF_8))).commit())
    }
    fun authenticates(credential: String): Boolean {
        val expected = prefs.getString("verifier", null) ?: return false
        return credential.matches(Regex("[0-9a-f]{64}")) && MessageDigest.isEqual(
            expected.toByteArray(), Protocol.hash(credential.toByteArray(Charsets.UTF_8)).toByteArray())
    }
    fun forget() { check(prefs.edit().remove("paired_name").remove("verifier").commit()) }
}
