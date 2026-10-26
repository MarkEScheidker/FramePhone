package com.example.framephone.bluetooth

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.bluetooth.*
import android.content.Context
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
    private var client: BleClient? = null
    private val gyro = ArrayDeque<BleProtocol.Gyro>()
    @Synchronized fun start(context: Context, latest: (String) -> JSONObject?) {
        if (client != null || context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return
        val address = SettingsStore(context).bluetoothAddress() ?: return
        client = BleClient(context.applicationContext, address, latest)
    }
    @Synchronized fun close() { client?.close(); client = null; synchronized(gyro) { gyro.clear() } }
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
                        private val latest: (String) -> JSONObject?) {
    private val worker = HandlerThread("phone-bluetooth").apply { start() }
    private val handler = Handler(worker.looper)
    private val store = SettingsStore(context)
    @Volatile private var closed = false
    private var gatt: BluetoothGatt? = null
    private var control: BluetoothGattCharacteristic? = null
    private var pose: BluetoothGattCharacteristic? = null
    private var mtu = 23
    private var pin = ""
    private var host = ""
    private var bootstrapHost = ""
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

    fun identity(value: String, endpoint: String) { handler.post {
        val changed = pin != value || host != endpoint
        pin = value; host = endpoint
        if (changed && session == null) nextSetupRead = 0
    } }
    fun session(value: String?) { handler.post {
        if (session != value) {
            session = value; bound = false; lastPose = ""
            nextSetupRead = 0
            if (value != null && control != null) needsRead = true
        }
    } }
    fun isBound(): Boolean = bound
    private fun begin(kind: String) { flight = kind; flightAt = SystemClock.elapsedRealtime() }
    private fun failed(detail: String) {
        bound = false
        runCatching { gatt?.disconnect() }; runCatching { gatt?.close() }
        gatt = null; control = null; pose = null; flight = null; binding = null; token = null
        chunks.clear()
        retryAt = SystemClock.elapsedRealtime()+retryMs
        retryMs = minOf(5000, retryMs*2)
        BluetoothPose.status = "Bluetooth retrying: $detail"
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
                failed("connection ended ($status)"); return@current
            }
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                BluetoothPose.status = "Bluetooth connected — negotiating"
                value.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
                runCatching { value.setPreferredPhy(BluetoothDevice.PHY_LE_2M_MASK, BluetoothDevice.PHY_LE_2M_MASK, BluetoothDevice.PHY_OPTION_NO_PREFERRED) }
                begin("mtu")
                if (!value.requestMtu(517)) failed("MTU request rejected")
            }
        } }
        override fun onMtuChanged(value: BluetoothGatt, size: Int, status: Int) { current(value) {
            if (status != BluetoothGatt.GATT_SUCCESS || size-3 < BleProtocol.POSE_BYTES) {
                failed("MTU too small for pose; Wi-Fi remains available"); return@current
            }
            mtu = size; begin("services")
            if (!value.discoverServices()) failed("service discovery rejected")
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
            if (status != BluetoothGatt.GATT_SUCCESS) { failed("bond/encryption approval required ($status)"); return@current }
            runCatching {
                val message = JSONObject(bytes.toString(Charsets.UTF_8))
                val peerAddress = message.getString("address")
                require(peerAddress.matches(Regex("[0-9A-Fa-f:]{17}")))
                if (message.getString("op") == "challenge" || (session == null && host != bootstrapHost)) {
                    require(pin.isNotEmpty() && host.isNotEmpty())
                    store.prepareBluetoothEnrollment()
                    val key = BleProtocol.unhex(store.bluetoothVerifier()!!)
                    val challenge = message.getString("challenge")
                    val request = JSONObject().put("op", "bootstrap").put("challenge", challenge)
                        .put("host", host).put("pin", pin)
                        .put("proof", BleProtocol.proof(key, BleProtocol.bootstrapText(challenge, peerAddress, pin, host)))
                    store.pendingBluetoothCredential()?.let { request.put("credential", it) }
                    bootstrapHost = host
                    enqueue(request, "bootstrap")
                } else {
                    require(message.getString("op") == "ready")
                    binding = message.getString("binding"); token = message.getString("token")
                    session?.let { sessionId ->
                        enqueue(JSONObject().put("op", "bind").put("binding", binding).put("session", sessionId)
                            .put("proof", BleProtocol.proof(BleProtocol.unhex(token!!), sessionId)), "bind")
                    }
                    BluetoothPose.status = "Bluetooth authenticated — waiting for Wi-Fi session"
                }
            }.onFailure { failed("setup rejected (${it.javaClass.simpleName})") }
        } }
        override fun onCharacteristicRead(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) =
            read(value, characteristic, characteristic.value ?: byteArrayOf(), status)
        override fun onCharacteristicRead(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, bytes: ByteArray, status: Int) =
            read(value, characteristic, bytes, status)
        override fun onCharacteristicWrite(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) { current(value) {
            flight = null
            if (status != BluetoothGatt.GATT_SUCCESS) { failed("write failed ($status)"); return@current }
            if (characteristic.uuid == BleProtocol.CONTROL && chunks.isEmpty()) {
                if (completion == "bootstrap") { store.bluetoothEnrollmentAccepted(); needsRead = true }
                if (completion == "bind") { bound = true; BluetoothPose.status = "Tracking over Bluetooth LE" }
                completion = ""
            }
        } }
    }
    private val tick = object : Runnable {
        override fun run() {
            if (closed) return
            try {
                val now = SystemClock.elapsedRealtime()
                if (flight != null && now-flightAt > if (flight == "pose") 300 else 15_000) failed("operation timed out")
                if (gatt == null && now >= retryAt) {
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
                if (flight == null && control != null) {
                    if (chunks.isNotEmpty()) {
                        begin("control")
                        if (!write(control!!, chunks.removeFirst(), true)) failed("control busy")
                    } else if (needsRead && pin.isNotEmpty() && host.isNotEmpty()) {
                        needsRead = false; begin("read")
                        if (gatt?.readCharacteristic(control) != true) failed("control read busy")
                    } else if (bound && pose != null) {
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
                bound -> 4L
                gatt == null -> 200L
                flight in listOf("connect", "mtu", "services") -> 50L
                else -> 10L
            }
            handler.postDelayed(this, delay)
        }
    }
    init { handler.post(tick) }
    fun close() { handler.post {
        closed = true; bound = false
        runCatching { gatt?.disconnect() }; runCatching { gatt?.close() }
        handler.removeCallbacksAndMessages(null); worker.quitSafely()
        BluetoothPose.status = "Bluetooth disconnected"
    } }
}
