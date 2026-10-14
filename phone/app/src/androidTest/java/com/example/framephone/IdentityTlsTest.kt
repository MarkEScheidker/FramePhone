package com.example.framephone

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.framephone.link.Identity
import com.example.framephone.link.TlsSelfCheck
import org.junit.Test
import org.junit.runner.RunWith

/** Device regression: exercise the actual Keystore key and Conscrypt TLS signatures. */
@RunWith(AndroidJUnit4::class)
class IdentityTlsTest {
    @Test fun persistentAndroidIdentityCompletesPinnedTls13() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val identity = Identity()
        if (identity.replacedLegacyIdentity) {
            SettingsStore(context).forget()
            identity.retireLegacyIdentity()
        }
        TlsSelfCheck.verify(identity.context(), identity.pin)
    }
}
