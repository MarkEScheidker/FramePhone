package com.example.framephone.link

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.math.BigInteger
import java.net.Socket
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Principal
import java.security.PrivateKey
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import java.util.Date
import javax.net.ssl.SSLContext
import javax.net.ssl.X509ExtendedKeyManager
import javax.security.auth.x500.X500Principal

/** The private identity key never leaves Android Keystore. */
class Identity {
    private val alias = "framephone-lan-v1"
    private val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    init {
        if (!store.containsAlias(alias)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
                initialize(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                    .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                    .setDigests(KeyProperties.DIGEST_SHA256)
                    .setCertificateSubject(X500Principal("CN=FramePhone"))
                    .setCertificateSerialNumber(BigInteger.ONE)
                    .setCertificateNotBefore(Date(0))
                    .setCertificateNotAfter(Date(4102444800000L)).build())
                generateKeyPair()
            }
        }
    }
    val pin: String = Protocol.hash(store.getCertificate(alias).encoded)
    fun context(): SSLContext {
        val manager = object : X509ExtendedKeyManager() {
            override fun getPrivateKey(alias: String?) = store.getKey(this@Identity.alias, null) as PrivateKey
            override fun getCertificateChain(alias: String?) = arrayOf(store.getCertificate(this@Identity.alias) as X509Certificate)
            override fun getServerAliases(keyType: String?, issuers: Array<out Principal>?) =
                if (keyType == "EC") arrayOf(alias) else null
            override fun chooseServerAlias(keyType: String?, issuers: Array<out Principal>?, socket: Socket?) =
                if (keyType == "EC") alias else null
            override fun getClientAliases(keyType: String?, issuers: Array<out Principal>?) = null
            override fun chooseClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, socket: Socket?) = null
        }
        return SSLContext.getInstance("TLSv1.3").apply { init(arrayOf(manager), null, null) }
    }
}
