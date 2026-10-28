package com.example.framephone.bluetooth

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.bluetooth.*
import android.content.Context
import android.content.BroadcastReceiver
import android.content.Intent
import android.content.IntentFilter
import androidx.core.content.ContextCompat
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import com.example.framephone.SettingsStore
import org.json.JSONObject
import java.util.ArrayDeque

/** One in-flight GATT operation; pull the latest source pose after completion. */
object BluetoothPose {
    @Volatile var status = "Bluetooth not associated"
        internal set
    @Volatile var lastFailure = ""
        internal set
    @Volatile var pairingNeedsAttention = false
        internal set
    @Volatile var pairingEvents = ""
        private set
    private val events = ArrayDeque<String>()
    @Synchronized internal fun record(event: String) {
        val line = "${SystemClock.elapsedRealtime()} ms: $event"
        events.addLast(line)
        while (events.size > 48) events.removeFirst()
        pairingEvents = events.joinToString("\n")
        android.util.Log.i("FramePhoneBluetooth", line)
    }
    private var client: BleClient? = null
    private val gyro = ArrayDeque<BleProtocol.Gyro>()
    @Synchronized fun start(context: Context, latest: (String) -> JSONObject?, bondLost: () -> Unit = {}) {
        if (client != null || context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return
        val address = SettingsStore(context).bluetoothAddress() ?: return
        pairingNeedsAttention = false
        client = BleClient(context.applicationContext, address, latest, bondLost)
    }
    @Synchronized fun close() { client?.close(); client = null; synchronized(gyro) { gyro.clear() } }
    @Synchronized fun retryPairing() { client?.retryPairing() }
    @Synchronized fun retryConnection() { client?.retryConnection() }
    @Synchronized fun identity(pin: String, host: String) { client?.identity(pin, host) }
    @Synchronized fun session(value: String?) { client?.session(value) }
    @Synchronized fun isBound(): Boolean = client?.isBound() == true
    fun gyro(time: Long, value: FloatArray) {
        if (value.size != 3 || value.any { !it.isFinite() } || value.sumOf { it.toDouble()*it } > 1225) return
        synchronized(gyro) {
            if (gyro.isNotEmpty() && time <= gyro.last.time) return
            gyro.addLast(BleProtocol.Gyro(time, value.copyOf()))
            while (gyro.size > 40 || time-gyro.first.time > 200_000_000) gyro.removeFirst()
        }
    }
    internal fun samples(): List<BleProtocol.Gyro> = synchronized(gyro) { gyro.toList() }
}

// The owner checks CONNECT before creating this worker. Revocation is handled
// by the operation error/retry path; it never changes Wi-Fi authentication.
@SuppressLint("MissingPermission")
@Suppress("DEPRECATION")
private class BleClient(private val context: Context, private val address: String,
                        private val latest: (String) -> JSONObject?, private val bondLost: () -> Unit) {
    private val worker = HandlerThread("phone-bluetooth").apply { start() }
    private val handler = Handler(worker.looper)
    private val store = SettingsStore(context)
    private val bondGate = BondGate()
    @Volatile private var closed = false
    private var gatt: BluetoothGatt? = null
    private var control: BluetoothGattCharacteristic? = null
    private var pose: BluetoothGattCharacteristic? = null
    private var mtu = 23
    private var mtuKnown = false
    private var poseAvailable = false
    private var pin = ""
    private var host = ""
    private var bootstrapHost = ""
    private var setupAttempted = false
    private var waitingBootstrapReady = false
    private var bindSession: String? = null
    private var session: String? = null
    private var binding: String? = null
    private var token: String? = null
    private var lastPose = ""
    private var flight: String? = null
    private var flightAt = 0L
    private var retryAt = 0L
    private var retryMs = 1000L
    private var fragmentId = 0
    private var chunks = ArrayDeque<ByteArray>()
    @Volatile private var bound = false
    private var needsRead = false
    private var nextSetupRead = 0L
    private var wifiWaitingAt = 0L
    private var bondStartedAt = 0L

    fun retryPairing() { handler.post {
        if (bondGate.waiting) return@post
        failed("Retrying saved connection")
        bondGate.retry()
        BluetoothPose.pairingNeedsAttention = false
        retryAt = 0
    } }
    fun retryConnection() { handler.post {
        if (session == null && !bondGate.blocked && !bondGate.waiting) {
            // Re-advertise the authenticated route even if the address did not
            // change. This wakes Frame's automatic Wi-Fi retry on each unlock.
            bootstrapHost = ""
            nextSetupRead = 0
            needsRead = true
            retryAt = 0
        }
    } }
    fun identity(value: String, endpoint: String) { handler.post {
        val changed = pin != value || host != endpoint
        pin = value; host = endpoint
        if (changed && session == null) nextSetupRead = 0
    } }
    fun session(value: String?) { handler.post {
        if (session != value) {
            session = value; bound = false; lastPose = ""
            nextSetupRead = 0
            wifiWaitingAt = if (value == null) SystemClock.elapsedRealtime() else 0
            if (value != null && control != null) needsRead = true
        }
    } }
    fun isBound(): Boolean = bound && poseAvailable && bondGate.ready
    private fun begin(kind: String) { flight = kind; flightAt = SystemClock.elapsedRealtime() }
    private fun releaseGatt() {
        bondGate.disconnected()
        bound = false
        runCatching { gatt?.disconnect() }; runCatching { gatt?.close() }
        gatt = null; control = null; pose = null; flight = null; binding = null; token = null
        chunks.clear()
        mtu = 23; mtuKnown = false; poseAvailable = false
        setupAttempted = false; waitingBootstrapReady = false; bindSession = null
        wifiWaitingAt = 0
    }
    private fun failed(detail: String) {
        BluetoothPose.lastFailure = "$detail during ${flight ?: if (bondGate.waiting) "bond" else "connection"}"
        BluetoothPose.record(BluetoothPose.lastFailure)
        releaseGatt()
        retryAt = SystemClock.elapsedRealtime()+retryMs
        retryMs = minOf(5000, retryMs*2)
        BluetoothPose.status = if (bondGate.waiting) "Finishing Bluetooth pairing — keep the confirmation open"
            else "Bluetooth retrying: ${BluetoothPose.lastFailure}"
    }
    private fun securityFailed(detail: String) {
        bondGate.reject()
        failed(detail)
        BluetoothPose.pairingNeedsAttention = true
        bondLost()
        BluetoothPose.status = "$detail — tap Retry connection; saved pairing is kept"
    }
    private fun applicationFailed(detail: String) {
        bondGate.reject()
        failed(detail)
        BluetoothPose.pairingNeedsAttention = true
        BluetoothPose.status = detail
    }
    private fun bondState(device: BluetoothDevice) = when (device.bondState) {
        BluetoothDevice.BOND_BONDED -> BondGate.Bond.BONDED
        BluetoothDevice.BOND_BONDING -> BondGate.Bond.BONDING
        else -> BondGate.Bond.NONE
    }
    private fun negotiate(value: BluetoothGatt) {
        if (gatt !== value || !bondGate.ready) return
        bondStartedAt = 0
        BluetoothPose.pairingNeedsAttention = false
        BluetoothPose.status = "Bluetooth paired — finishing connection"
        begin("settling")
        // Bond completion precedes encryption/service-change processing on
        // Android. Fence this delay to the same connection and operation.
        handler.postDelayed({
            if (!closed && gatt === value && flight == "settling" && bondGate.ready) discover(value, mtu)
        }, 1600)
    }
    private fun discover(value: BluetoothGatt, size: Int) {
        mtu = size.coerceIn(23, 517)
        poseAvailable = mtu-3 >= BleProtocol.POSE_BYTES
        begin("services")
        if (!value.discoverServices()) failed("service discovery rejected")
    }
    private fun awaitBond(device: BluetoothDevice, create: Boolean) {
        begin("bond")
        if (bondStartedAt == 0L) bondStartedAt = SystemClock.elapsedRealtime()
        BluetoothPose.status = "Check the number shown on Steam Frame, then tap Pair on this phone"
        if (create) BluetoothPose.record("createBond requested; device type=${device.type}")
        if (create && !device.createBond()) {
            when (bondState(device)) {
                BondGate.Bond.BONDED -> {
                    bondGate.changed(BondGate.Bond.BONDED)
                    flight = null; bondStartedAt = 0
                }
                BondGate.Bond.BONDING -> Unit
                else -> securityFailed("Could not start Bluetooth pairing")
            }
        }
    }
    private val bondChanges = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val device = if (Build.VERSION.SDK_INT >= 33)
                intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                else intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE)
            if (!device?.address.equals(address, true)) return
            if (intent.action == BluetoothDevice.ACTION_PAIRING_REQUEST) {
                BluetoothPose.record("pairing prompt variant=${intent.getIntExtra(BluetoothDevice.EXTRA_PAIRING_VARIANT, -1)}")
                return
            }
            if (Build.VERSION.SDK_INT >= 36 && intent.action == BluetoothDevice.ACTION_ENCRYPTION_CHANGE) {
                val transport = when (intent.getIntExtra(BluetoothDevice.EXTRA_TRANSPORT, 0)) {
                    BluetoothDevice.TRANSPORT_LE -> "LE"
                    BluetoothDevice.TRANSPORT_BREDR -> "Classic"
                    else -> "unknown"
                }
                BluetoothPose.record("encryption $transport enabled=${intent.getBooleanExtra(BluetoothDevice.EXTRA_ENCRYPTION_ENABLED, false)} status=${intent.getIntExtra(BluetoothDevice.EXTRA_ENCRYPTION_STATUS, -1)}")
                return
            }
            if (Build.VERSION.SDK_INT >= 36 && intent.action == BluetoothDevice.ACTION_KEY_MISSING) {
                BluetoothPose.record("Bluetooth reports missing peer keys")
                return
            }
            val reported = when (intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, BluetoothDevice.ERROR)) {
                BluetoothDevice.BOND_BONDED -> BondGate.Bond.BONDED
                BluetoothDevice.BOND_BONDING -> BondGate.Bond.BONDING
                BluetoothDevice.BOND_NONE -> BondGate.Bond.NONE
                else -> return
            }
            handler.post {
                if (closed) return@post
                BluetoothPose.record("bond $reported; operation=${flight ?: "idle"}")
                when (bondGate.changed(reported)) {
                    BondGate.Action.NEGOTIATE -> {
                        // Reconnect after a key change; this socket predates it.
                        releaseGatt()
                        BluetoothPose.status = "Bluetooth paired — reconnecting securely"
                        BluetoothPose.pairingNeedsAttention = false
                        bondStartedAt = 0; retryAt = SystemClock.elapsedRealtime()+300
                    }
                    BondGate.Action.BLOCK -> securityFailed("Bluetooth pairing cancelled or removed")
                    BondGate.Action.RETRY -> if (gatt == null) {
                        BluetoothPose.pairingNeedsAttention = false; bondStartedAt = 0; flight = null
                        retryAt = SystemClock.elapsedRealtime()+300
                    }
                    else -> Unit
                }
            }
        }
    }
    private fun enqueue(message: JSONObject, kind: String) {
        chunks = ArrayDeque(BleProtocol.fragments(message.toString().toByteArray(Charsets.UTF_8), mtu, ++fragmentId))
        flight = null
        completion = kind
    }
    private var completion = ""
    private fun write(characteristic: BluetoothGattCharacteristic, bytes: ByteArray, response: Boolean): Boolean {
        val type = if (response) BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT else BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
        val current = gatt ?: return false
        return if (Build.VERSION.SDK_INT >= 33)
            current.writeCharacteristic(characteristic, bytes, type) == BluetoothStatusCodes.SUCCESS
        else { characteristic.writeType = type; characteristic.value = bytes; current.writeCharacteristic(characteristic) }
    }
    private val callback = object : BluetoothGattCallback() {
        private fun current(value: BluetoothGatt, action: () -> Unit) = handler.post { if (!closed && gatt === value) action() }
        override fun onConnectionStateChange(value: BluetoothGatt, status: Int, newState: Int) { current(value) {
            BluetoothPose.record("GATT state=$newState status=$status; operation=${flight ?: "idle"}")
            if (status != BluetoothGatt.GATT_SUCCESS || newState == BluetoothProfile.STATE_DISCONNECTED) {
                if (status == 5 || status == 137) securityFailed("Bluetooth authentication failed ($status)")
                else failed("connection ended ($status)")
                return@current
            }
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                when (bondGate.connected(bondState(value.device))) {
                    BondGate.Action.NEGOTIATE -> negotiate(value)
                    BondGate.Action.CREATE_BOND -> {
                        releaseGatt()
                        awaitBond(value.device, create = true)
                    }
                    BondGate.Action.WAIT -> if (bondGate.waiting) awaitBond(value.device, create = false)
                    else -> securityFailed("Bluetooth pairing needs attention")
                }
            }
        } }
        override fun onMtuChanged(value: BluetoothGatt, size: Int, status: Int) { current(value) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                mtu = size.coerceIn(23, 517)
                mtuKnown = true
                poseAvailable = mtu-3 >= BleProtocol.POSE_BYTES
            }
            if (flight != "mtu" || !bondGate.ready) return@current
            if (BondGate.securityFailure(status)) {
                securityFailed("Bluetooth authentication failed ($status)"); return@current
            }
            flight = null; needsRead = true
        } }
        override fun onServicesDiscovered(value: BluetoothGatt, status: Int) { current(value) {
            if (flight != "services" || !bondGate.ready) return@current
            val service = value.getService(BleProtocol.SERVICE)
            control = service?.getCharacteristic(BleProtocol.CONTROL)
            pose = service?.getCharacteristic(BleProtocol.POSE)
            if (status != BluetoothGatt.GATT_SUCCESS || control == null || pose == null) {
                failed("FramePhone service unavailable ($status)"); return@current
            }
            if (mtuKnown) { flight = null; needsRead = true }
            else {
                begin("mtu")
                if (!value.requestMtu(517)) { mtuKnown = true; flight = null; needsRead = true }
            }
        } }
        private fun read(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, bytes: ByteArray, status: Int) { current(value) {
            if (characteristic.uuid != BleProtocol.CONTROL || flight != "read") return@current
            if (binding == null || status != BluetoothGatt.GATT_SUCCESS)
                BluetoothPose.record("protected LE read status=$status; bond=${bondState(value.device)}")
            if (status != BluetoothGatt.GATT_SUCCESS) {
                if (BondGate.securityFailure(status)) securityFailed("Bluetooth authentication failed ($status)")
                else failed("GATT read failed ($status)")
                return@current
            }
            flight = null
            runCatching {
                val message = JSONObject(bytes.toString(Charsets.UTF_8))
                if (message.optString("op") == "error") {
                    if (message.optString("code") == "pairing_mismatch") {
                        store.prepareBluetoothEnrollment(replace = true)
                        bootstrapHost = ""; setupAttempted = false; waitingBootstrapReady = false; needsRead = true
                        BluetoothPose.status = "Confirm replacement of the saved phone on Steam Frame"
                    } else applicationFailed(when (message.optString("code")) {
                        "headset_paired" -> "Steam Frame has another saved phone — use Forget phone on Steam Frame first"
                        "pairing_rejected" -> "Pairing declined on Steam Frame — tap Retry connection to try again"
                        "saved_pairing_invalid" -> "Saved pairing is unreadable on Steam Frame — use Forget phone there, then retry"
                        "pairing_storage_failed" -> "Steam Frame could not save pairing — check its configuration permissions"
                        else -> "Pairing versions are incompatible — update both apps and retry"
                    })
                    return@current
                }
                val peerAddress = message.getString("address")
                require(peerAddress.matches(Regex("[0-9A-Fa-f:]{17}")))
                if (message.getString("op") == "challenge" || !setupAttempted || (session == null && host != bootstrapHost)) {
                    require(pin.isNotEmpty() && host.isNotEmpty())
                    store.prepareBluetoothEnrollment(replace = !message.optBoolean("paired", true))
                    val key = BleProtocol.unhex(store.bluetoothVerifier()!!)
                    val challenge = message.getString("challenge")
                    val request = JSONObject().put("op", "bootstrap").put("challenge", challenge)
                        .put("host", host).put("pin", pin)
                        .put("proof", BleProtocol.proof(key, BleProtocol.bootstrapText(challenge, peerAddress, pin, host)))
                    store.pendingBluetoothCredential()?.let { request.put("credential", it) }
                    bootstrapHost = host
                    setupAttempted = true; waitingBootstrapReady = true
                    enqueue(request, "bootstrap")
                } else {
                    require(message.getString("op") == "ready")
                    binding = message.getString("binding"); token = message.getString("token")
                    if (waitingBootstrapReady) {
                        store.bluetoothEnrollmentAccepted()
                        waitingBootstrapReady = false
                    }
                    session?.let { sessionId ->
                        bindSession = sessionId
                        enqueue(JSONObject().put("op", "bind").put("binding", binding).put("session", sessionId)
                            .put("proof", BleProtocol.proof(BleProtocol.unhex(token!!), sessionId)), "bind")
                    }
                    if (session == null && wifiWaitingAt == 0L) wifiWaitingAt = SystemClock.elapsedRealtime()
                    if (session == null) waitingStatus(SystemClock.elapsedRealtime())
                }
            }.onFailure { applicationFailed("Pairing data was rejected — update both apps and retry pairing") }
        } }
        override fun onCharacteristicRead(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) =
            read(value, characteristic, characteristic.value ?: byteArrayOf(), status)
        override fun onCharacteristicRead(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, bytes: ByteArray, status: Int) =
            read(value, characteristic, bytes, status)
        override fun onCharacteristicWrite(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) { current(value) {
            if ((characteristic.uuid == BleProtocol.CONTROL && flight != "control") ||
                (characteristic.uuid == BleProtocol.POSE && flight != "pose")) return@current
            flight = null
            if (status != BluetoothGatt.GATT_SUCCESS) {
                if (BondGate.securityFailure(status)) securityFailed("Bluetooth authentication failed ($status)")
                else failed("GATT write failed ($status)")
                return@current
            }
            if (characteristic.uuid == BleProtocol.CONTROL && chunks.isEmpty()) {
                if (completion == "bootstrap") { needsRead = true }
                if (completion == "bind") {
                    bound = bindSession == session && session != null
                    if (bound) {
                        BluetoothPose.lastFailure = ""
                        retryMs = 1000
                        runCatching { value.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH) }
                        runCatching { value.setPreferredPhy(BluetoothDevice.PHY_LE_2M_MASK, BluetoothDevice.PHY_LE_2M_MASK, BluetoothDevice.PHY_OPTION_NO_PREFERRED) }
                        BluetoothPose.status = if (poseAvailable) "Tracking over Bluetooth LE" else "Bluetooth paired — motion uses Wi-Fi"
                    } else needsRead = true
                }
                completion = ""
            }
        } }
    }
    private fun waitingStatus(now: Long) {
        BluetoothPose.status = if (wifiWaitingAt > 0 && now-wifiWaitingAt >= 5000)
            "Bluetooth connected — Wi-Fi unavailable; retrying automatically"
        else "Bluetooth connected — Wi-Fi connecting automatically"
    }
    private val tick = object : Runnable {
        override fun run() {
            if (closed) return
            try {
                val now = SystemClock.elapsedRealtime()
                val timeout = when (flight) { "bond", "control", "read" -> 95_000L; "pose" -> 300L; "mtu" -> 2_000L; else -> 15_000L }
                if (bondGate.waiting && bondStartedAt == 0L) bondStartedAt = now
                if (bondGate.waiting && now-bondStartedAt > 95_000) securityFailed("Bluetooth pairing timed out")
                if (flight != null && now-flightAt > timeout) {
                    if (now-flightAt <= 95_000 && bondGate.waiting)
                        BluetoothPose.status = "Check the number shown on Steam Frame, then tap Pair on this phone"
                    else if (flight == "mtu") {
                        // Optional packet-size optimization cannot restart a
                        // successful bond. Small packets still bootstrap TLS.
                        mtuKnown = true; flight = null; needsRead = true
                    }
                    else if (flight == "bond") securityFailed("Bluetooth pairing timed out")
                    else if (flight == "control") applicationFailed("Pairing did not complete — check Steam Frame and tap Retry connection")
                    else failed("operation timed out")
                }
                if (!bondGate.blocked && !bondGate.waiting && gatt == null && now >= retryAt) {
                    val adapter = context.getSystemService(BluetoothManager::class.java).adapter
                    if (adapter?.isEnabled == true) {
                        val device = adapter.getRemoteDevice(address)
                        when (bondGate.prepare(bondState(device))) {
                            BondGate.Action.CREATE_BOND -> awaitBond(device, create = true)
                            BondGate.Action.WAIT -> if (bondGate.waiting) awaitBond(device, create = false)
                            BondGate.Action.CONNECT -> {
                                BluetoothPose.record("connect LE; bond=${bondState(device)}")
                                begin("connect")
                                gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
                            }
                            else -> Unit
                        }
                    } else retryAt = now+2000
                }
                // Retry bootstrap while TLS is absent, including after a LAN
                // address change. A ready read alone never authorizes poses.
                if (session == null && !bound && now >= nextSetupRead && control != null) {
                    needsRead = true
                    nextSetupRead = now+1000
                }
                if (session == null && binding != null && gatt != null) waitingStatus(now)
                if (flight == null && control != null && bondGate.ready) {
                    if (chunks.isNotEmpty()) {
                        begin("control")
                        if (!write(control!!, chunks.removeFirst(), true)) failed("control busy")
                    } else if (needsRead && pin.isNotEmpty() && host.isNotEmpty()) {
                        needsRead = false; begin("read")
                        if (gatt?.readCharacteristic(control) != true) failed("control read busy")
                    } else if (bound && poseAvailable && pose != null) {
                        // Pull from the source mailbox independently of the
                        // Wi-Fi writer; congestion there cannot queue BLE poses.
                        val value = session?.let(latest)
                        val encoded = value?.toString()
                        if (value != null && encoded != lastPose) {
                            if (value.getString("session") == session) {
                                begin("pose")
                                if (write(pose!!, BleProtocol.pose(value, BluetoothPose.samples(), mtu-3), false)) lastPose = encoded!!
                                else failed("pose busy")
                            }
                        }
                    }
                }
            } catch (error: Exception) { failed(error.javaClass.simpleName) }
            val delay = when {
                bound && poseAvailable -> 4L
                bound -> 200L
                gatt == null -> 200L
                flight in listOf("connect", "bond", "settling", "mtu", "services") -> 50L
                else -> 10L
            }
            handler.postDelayed(this, delay)
        }
    }
    init {
        // Bluetooth broadcasts can come from the privileged Bluetooth process,
        // not only system UID; filter by the selected companion address.
        val filter = IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED)
        filter.addAction(BluetoothDevice.ACTION_PAIRING_REQUEST)
        if (Build.VERSION.SDK_INT >= 36) {
            filter.addAction(BluetoothDevice.ACTION_ENCRYPTION_CHANGE)
            filter.addAction(BluetoothDevice.ACTION_KEY_MISSING)
        }
        ContextCompat.registerReceiver(context, bondChanges, filter, ContextCompat.RECEIVER_EXPORTED)
        handler.post(tick)
    }
    fun close() { handler.post {
        closed = true; bound = false
        runCatching { gatt?.disconnect() }; runCatching { gatt?.close() }
        context.unregisterReceiver(bondChanges)
        handler.removeCallbacksAndMessages(null); worker.quitSafely()
        BluetoothPose.status = "Bluetooth disconnected"
    } }
}
