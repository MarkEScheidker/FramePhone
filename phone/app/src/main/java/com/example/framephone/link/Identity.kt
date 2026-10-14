package com.example.framephone.link

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.spec.ECGenParameterSpec
import java.util.Date
import javax.net.ssl.SSLContext
import javax.net.ssl.KeyManagerFactory
import javax.security.auth.x500.X500Principal

/** The private identity key never leaves Android Keystore. */
class Identity {
    private val alias = "framephone-lan-v2"
    private val legacyAlias = "framephone-lan-v1"
    private val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    val replacedLegacyIdentity = store.containsAlias(legacyAlias)
    init {
        if (!store.containsAlias(alias)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
                initialize(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                    .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                    // Conscrypt signs its already-hashed TLS transcript with NONEwithECDSA.
                    .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256)
                    .setCertificateSubject(X500Principal("CN=FramePhone"))
                    .setCertificateSerialNumber(BigInteger.ONE)
                    .setCertificateNotBefore(Date(0))
                    .setCertificateNotAfter(Date(4102444800000L)).build())
                generateKeyPair()
            }
        }
    }
    val pin: String = Protocol.hash(store.getCertificate(alias).encoded)
    fun retireLegacyIdentity() {
        if (store.containsAlias(legacyAlias)) store.deleteEntry(legacyAlias)
    }
    fun context(): SSLContext {
        val managers = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply {
            init(store, null)
        }
        return SSLContext.getInstance("TLSv1.3").apply { init(managers.keyManagers, null, null) }
    }
}
