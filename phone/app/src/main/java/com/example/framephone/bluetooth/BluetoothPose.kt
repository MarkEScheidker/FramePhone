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
    @Volatile var pairingNeedsAttention = false
        internal set
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

    fun retryPairing() { handler.post {
        bondGate.retry()
        BluetoothPose.pairingNeedsAttention = false
        retryAt = 0
    } }
    fun retryConnection() { handler.post {
        if (session == null && !bondGate.blocked) {
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
    fun isBound(): Boolean = bound && poseAvailable
    private fun begin(kind: String) { flight = kind; flightAt = SystemClock.elapsedRealtime() }
    private fun failed(detail: String) {
        bondGate.disconnected()
        bound = false
        runCatching { gatt?.disconnect() }; runCatching { gatt?.close() }
        gatt = null; control = null; pose = null; flight = null; binding = null; token = null
        chunks.clear()
        setupAttempted = false; waitingBootstrapReady = false; bindSession = null
        wifiWaitingAt = 0
        retryAt = SystemClock.elapsedRealtime()+retryMs
        retryMs = minOf(5000, retryMs*2)
        BluetoothPose.status = "Bluetooth retrying: $detail"
    }
    private fun securityFailed(detail: String, repairBond: Boolean = true) {
        bondGate.reject()
        failed(detail)
        BluetoothPose.pairingNeedsAttention = true
        bondLost()
        BluetoothPose.status = if (repairBond) "$detail — remove the old Steam Frame bond on both devices and pair again"
            else "$detail — tap Retry pairing when ready"
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
        BluetoothPose.pairingNeedsAttention = false
        BluetoothPose.status = "Bluetooth paired — negotiating"
        value.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
        runCatching { value.setPreferredPhy(BluetoothDevice.PHY_LE_2M_MASK, BluetoothDevice.PHY_LE_2M_MASK, BluetoothDevice.PHY_OPTION_NO_PREFERRED) }
        begin("mtu")
        if (!value.requestMtu(517)) discover(value, 23)
    }
    private fun discover(value: BluetoothGatt, size: Int) {
        mtu = size.coerceIn(23, 517)
        poseAvailable = mtu-3 >= BleProtocol.POSE_BYTES
        begin("services")
        if (!value.discoverServices()) failed("service discovery rejected")
    }
    private val bondChanges = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val device = if (Build.VERSION.SDK_INT >= 33)
                intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                else intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE)
            if (!device?.address.equals(address, true)) return
            handler.post {
                if (closed) return@post
                when (bondGate.changed(bondState(device!!))) {
                    BondGate.Action.NEGOTIATE -> gatt?.let { negotiate(it) }
                    BondGate.Action.BLOCK -> securityFailed("Bluetooth pairing cancelled or removed", repairBond = false)
                    BondGate.Action.RETRY -> if (gatt == null) {
                        BluetoothPose.pairingNeedsAttention = false; retryAt = 0
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
            if (status != BluetoothGatt.GATT_SUCCESS || newState == BluetoothProfile.STATE_DISCONNECTED) {
                if (status == 5 || status == 137) securityFailed("Bluetooth authentication failed ($status)")
                else failed("connection ended ($status)")
                return@current
            }
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                when (bondGate.connected(bondState(value.device))) {
                    BondGate.Action.NEGOTIATE -> negotiate(value)
                    BondGate.Action.CREATE_BOND, BondGate.Action.WAIT -> {
                        begin("bond")
                        BluetoothPose.status = "Compare and approve the Bluetooth number on both devices"
                        if (value.device.bondState == BluetoothDevice.BOND_NONE && !value.device.createBond()) {
                            when (bondState(value.device)) {
                                BondGate.Bond.BONDED -> { bondGate.changed(BondGate.Bond.BONDED); negotiate(value) }
                                BondGate.Bond.BONDING -> Unit
                                else -> securityFailed("Could not start Bluetooth pairing", repairBond = false)
                            }
                        }
                    }
                    else -> securityFailed("Bluetooth pairing needs attention")
                }
            }
        } }
        override fun onMtuChanged(value: BluetoothGatt, size: Int, status: Int) { current(value) {
            if (BondGate.securityFailure(status)) {
                securityFailed("Bluetooth authentication failed ($status)"); return@current
            }
            discover(value, if (status == BluetoothGatt.GATT_SUCCESS) size else 23)
        } }
        override fun onServicesDiscovered(value: BluetoothGatt, status: Int) { current(value) {
            val service = value.getService(BleProtocol.SERVICE)
            control = service?.getCharacteristic(BleProtocol.CONTROL)
            pose = service?.getCharacteristic(BleProtocol.POSE)
            if (status != BluetoothGatt.GATT_SUCCESS || control == null || pose == null) {
                failed("FramePhone service unavailable"); return@current
            }
            flight = null; needsRead = true; retryMs = 1000
        } }
        private fun read(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, bytes: ByteArray, status: Int) { current(value) {
            if (characteristic.uuid != BleProtocol.CONTROL) return@current
            flight = null
            if (status != BluetoothGatt.GATT_SUCCESS) {
                if (BondGate.securityFailure(status)) securityFailed("Bluetooth authentication failed ($status)")
                else failed("GATT read failed ($status)")
                return@current
            }
            runCatching {
                val message = JSONObject(bytes.toString(Charsets.UTF_8))
                if (message.optString("op") == "error") {
                    if (message.optString("code") == "pairing_mismatch") {
                        store.prepareBluetoothEnrollment(replace = true)
                        bootstrapHost = ""; setupAttempted = false; waitingBootstrapReady = false; needsRead = true
                        BluetoothPose.status = "Confirm replacement of the saved phone on Steam Frame"
                    } else applicationFailed(when (message.optString("code")) {
                        "pairing_rejected" -> "Pairing declined on Steam Frame — tap Retry pairing to try again"
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
                    if (bound) BluetoothPose.status = if (poseAvailable) "Tracking over Bluetooth LE" else
                        "Bluetooth paired — motion uses Wi-Fi"
                    else needsRead = true
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
                val timeout = when (flight) { "bond", "control", "read" -> 95_000L; "pose" -> 300L; else -> 15_000L }
                if (flight != null && now-flightAt > timeout) {
                    if (now-flightAt <= 95_000 && gatt?.device?.bondState == BluetoothDevice.BOND_BONDING)
                        BluetoothPose.status = "Compare and approve the Bluetooth number on both devices"
                    else if (flight == "bond") securityFailed("Bluetooth pairing timed out", repairBond = false)
                    else if (flight == "control") applicationFailed("Pairing did not complete — check Steam Frame and tap Retry pairing")
                    else failed("operation timed out")
                }
                if (!bondGate.blocked && gatt == null && now >= retryAt) {
                    val adapter = context.getSystemService(BluetoothManager::class.java).adapter
                    if (adapter?.isEnabled == true) {
                        begin("connect")
                        gatt = adapter.getRemoteDevice(address).connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
                    } else retryAt = now+2000
                }
                // Retry bootstrap while TLS is absent, including after a LAN
                // address change. A ready read alone never authorizes poses.
                if (session == null && !bound && now >= nextSetupRead && control != null) {
                    needsRead = true
                    nextSetupRead = now+1000
                }
                if (session == null && binding != null && gatt != null) waitingStatus(now)
                if (flight == null && control != null) {
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
                flight in listOf("connect", "mtu", "services") -> 50L
                else -> 10L
            }
            handler.postDelayed(this, delay)
        }
    }
    init {
        // Bluetooth broadcasts can come from the privileged Bluetooth process,
        // not only system UID; filter by the selected companion address.
        ContextCompat.registerReceiver(context, bondChanges,
            IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED), ContextCompat.RECEIVER_EXPORTED)
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
