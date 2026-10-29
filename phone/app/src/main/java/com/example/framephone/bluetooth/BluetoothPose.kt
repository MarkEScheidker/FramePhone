package com.example.framephone.bluetooth

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.*
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import androidx.core.content.ContextCompat
import com.example.framephone.SettingsStore
import com.example.framephone.Fiducial
import com.example.framephone.link.SensorFeed
import com.example.framephone.tracking.ArPoseState
import org.json.JSONObject
import java.security.SecureRandom
import java.util.ArrayDeque
import java.util.UUID
import javax.net.ssl.SSLContext

/** Bluetooth is a byte transport. TLS and explicit hash approval establish app trust. */
object BluetoothPose {
    data class Verification(val id: String, val code: String, val approved: Boolean = false)
    @Volatile var status = "Bluetooth disconnected"
        internal set
    @Volatile var lastFailure = ""
        internal set
    @Volatile var verification: Verification? = null
        internal set
    private var client: BleClient? = null
    private val gyro = ArrayDeque<BleProtocol.Gyro>()

    @Synchronized fun start(context: Context, latest: (String) -> JSONObject?, bondLost: () -> Unit = {},
                            trackingChanged: (Boolean) -> Unit = {}) {
        if (client != null || context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return
        val address = SettingsStore(context).bluetoothAddress() ?: return
        client = BleClient(context.applicationContext, address, latest, bondLost, trackingChanged)
    }
    @Synchronized fun close() {
        client?.close(); client = null; verification = null
        status = "Bluetooth disconnected"
        synchronized(gyro) { gyro.clear() }
    }
    @Synchronized fun retryConnection() { client?.refreshRoute() }
    @Synchronized fun identity(tls: SSLContext, pin: String, host: String) { client?.identity(tls, pin, host) }
    @Synchronized fun confirm(id: String, accepted: Boolean) { client?.confirm(id, accepted) }
    @Synchronized fun session(value: String?) { client?.session(value) }
    @Synchronized fun isBound() = client?.isBound() == true
    @Synchronized fun standalone() = client?.isStandalone() == true
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

@SuppressLint("MissingPermission")
@Suppress("DEPRECATION")
private class BleClient(private val context: Context, private val address: String,
                        private val latest: (String) -> JSONObject?, private val bondLost: () -> Unit,
                        private val trackingChanged: (Boolean) -> Unit) {
    private val worker = HandlerThread("phone-bluetooth").apply { start() }
    private val handler = Handler(worker.looper)
    private val store = SettingsStore(context)
    @Volatile private var closed = false
    @Volatile private var bound = false
    @Volatile private var standalone = false
    private var feed: SensorFeed? = null
    private var gyroStream = false
    private var blocked = false
    private var gatt: BluetoothGatt? = null
    private var control: BluetoothGattCharacteristic? = null
    private var pose: BluetoothGattCharacteristic? = null
    private var tlsContext: SSLContext? = null
    private var tls: BluetoothTls? = null
    private var pin = ""
    private var host = ""
    private var sentHost = ""
    private var session: String? = null
    private var lastPose = ""
    private var authenticated = false
    private var nonce = ""
    private var phoneApproved = false
    private var frameApproved = false
    private var credentialSent = false
    private var flight: String? = null
    private var flightAt = 0L
    private var retryAt = 0L
    private val controlReads = ControlReadSchedule()
    private var bindAt = 0L
    private var gyroAt = 0L
    private var lastGyro = 0L
    private var markerAt = 0L
    private var sensorAt = 0L
    private var mtu = 23
    private var messageId = 0
    private val writes = ArrayDeque<ByteArray>()

    fun identity(context: SSLContext, identity: String, endpoint: String) { handler.post {
        tlsContext = context; pin = identity; host = endpoint
    } }
    fun refreshRoute() { handler.post { sentHost = ""; controlReads.reset() } }
    fun session(value: String?) { handler.post {
        if (standalone) return@post
        session = value; bound = false; gyroStream = false; lastPose = ""; bindAt = 0; lastGyro = 0
    } }
    fun isBound() = !closed && bound && (standalone || mtu >= BleProtocol.POSE_BYTES+68)
    fun isStandalone() = !closed && standalone && bound
    fun confirm(id: String, accepted: Boolean) { handler.post {
        val request = BluetoothPose.verification
        if (closed || request?.id != id || request.approved) return@post
        phoneApproved = accepted
        BluetoothPose.verification = if (accepted) request.copy(approved = true) else null
        send(JSONObject().put("op", "confirm").put("accepted", accepted))
        if (accepted) {
            BluetoothPose.status = "Waiting for headset verification"
            finishEnrollment()
        } else {
            blocked = true
            BluetoothPose.status = "Verification declined"
        }
    } }

    private fun begin(operation: String) { flight = operation; flightAt = SystemClock.elapsedRealtime() }
    private fun release() {
        val wasStandalone = standalone && bound
        feed?.close(); feed = null
        runCatching { gatt?.disconnect() }; runCatching { gatt?.close() }
        gatt = null; control = null; pose = null; tls = null; flight = null
        writes.clear(); mtu = 23; bound = false; authenticated = false
        sentHost = ""; lastPose = ""; nonce = ""
        gyroStream = false; gyroAt = 0; lastGyro = 0
        controlReads.reset()
        standalone = false; session = null; markerAt = 0; sensorAt = 0
        phoneApproved = false; frameApproved = false; credentialSent = false
        if (!closed) BluetoothPose.verification = null
        if (wasStandalone) trackingChanged(false)
    }
    private fun fail(message: String, stop: Boolean = false) {
        if (closed) return
        BluetoothPose.lastFailure = message
        release(); blocked = blocked || stop; retryAt = SystemClock.elapsedRealtime()+1500
        BluetoothPose.status = if (blocked) message else "Bluetooth reconnecting"
        bondLost()
    }
    private fun send(message: JSONObject) {
        tls?.send(byteArrayOf(0)+message.toString().toByteArray(Charsets.UTF_8)) ?: error("TLS unavailable")
        flush()
    }
    private fun flush() {
        val bytes = tls?.take() ?: return
        if (bytes.isNotEmpty()) writes.addAll(BleProtocol.fragments(bytes, mtu, ++messageId))
    }
    private fun finishEnrollment() {
        if (!phoneApproved || !frameApproved || credentialSent) return
        store.prepareBluetoothEnrollment()
        credentialSent = true
        send(JSONObject().put("op", "paired").put("credential", store.pendingBluetoothCredential()))
    }
    private fun ready() {
        authenticated = true
        BluetoothPose.verification = null
        BluetoothPose.lastFailure = ""
        BluetoothPose.status = if (standalone) "Bluetooth secure — starting tracking" else "Bluetooth secure — Wi-Fi connecting"
        send(JSONObject().put("op", "ready").put("host", host).put("standalone_tracking", standalone))
        sentHost = host
        if (standalone) {
            val dimensions = store.dimensions() ?: error("Phone dimensions unavailable")
            val sensors = SensorFeed(context).also { feed = it }
            val id = UUID.randomUUID().toString()
            session = id
            val profile = JSONObject().put("type", "profile").put("version", 1)
                .put("session", id).put("dimensions", dimensions.json())
                .put("clock", "android_elapsed_realtime_ns").put("axes", "android_natural_device")
                .put("sensors", sensors.capabilities).put("marker_state_v1", true)
                .put("headset_presence_v1", true).put("arcore_pose_v1", true)
                .put("automatic_marker_v1", true)
                .apply { runCatching { Fiducial.currentProfile(context) }.getOrNull()?.let { put("fiducial", it) } }
            send(JSONObject().put("op", "tracking_profile").put("profile", profile))
        }
    }
    private fun message(bytes: ByteArray) {
        require(bytes.isNotEmpty() && bytes[0] == 0.toByte())
        val value = JSONObject(bytes.copyOfRange(1, bytes.size).toString(Charsets.UTF_8))
        when (value.getString("op")) {
            "hello" -> {
                require(value.getInt("version") == 2)
                standalone = value.optBoolean("standalone_tracking", false)
                if (value.getString("mode") == "reconnect") {
                    val credential = value.getString("credential")
                    if (store.authenticates(credential)) {
                        if (store.pendingBluetoothCredential() == credential) store.bluetoothEnrollmentAccepted()
                        else store.cancelBluetoothEnrollment()
                        ready()
                    } else send(JSONObject().put("op", "pair_required"))
                } else {
                    require(value.getString("mode") == "pair")
                    authenticated = false; bound = false
                    store.cancelBluetoothEnrollment()
                    nonce = value.getString("nonce")
                    val phoneNonce = BleProtocol.hex(ByteArray(32).also { SecureRandom().nextBytes(it) })
                    BluetoothPose.verification = BluetoothPose.Verification(nonce, BluetoothTls.code(pin, nonce, phoneNonce))
                    phoneApproved = false; frameApproved = false; credentialSent = false
                    BluetoothPose.status = "Compare the hash on both devices"
                    send(JSONObject().put("op", "verification").put("nonce", phoneNonce))
                }
            }
            "confirm" -> {
                frameApproved = value.getBoolean("accepted")
                if (!frameApproved) fail("Headset declined verification", stop = true) else finishEnrollment()
            }
            "enrolled" -> {
                check(!authenticated && phoneApproved && frameApproved && credentialSent)
                store.bluetoothEnrollmentAccepted()
                ready()
            }
            "bound" -> {
                if (value.getString("session") == session) {
                    val wasBound = bound
                    bound = value.getBoolean("accepted")
                    gyroStream = bound && value.optBoolean("gyro_stream", false)
                    if (standalone && wasBound != bound) trackingChanged(bound)
                }
                if (bound) BluetoothPose.status = if (isBound()) "Tracking over encrypted Bluetooth" else "Bluetooth secure — motion uses Wi-Fi"
            }
            "tracking" -> {
                val command = value.getJSONObject("message")
                require(standalone && bound && command.getString("session") == session)
                when (command.getString("type")) {
                    "ping" -> {
                        val received = SystemClock.elapsedRealtimeNanos()
                        send(JSONObject().put("op", "tracking").put("message", JSONObject()
                            .put("type", "pong").put("session", session).put("h0", command.getLong("h0"))
                            .put("p1", received).put("p2", SystemClock.elapsedRealtimeNanos())))
                    }
                    "headset_presence" -> ArPoseState.headsetPresence(command.getBoolean("worn"))
                    "alignment_accepted" -> ArPoseState.acknowledge(command)
                    "alignment_lost" -> ArPoseState.alignmentLost(command)
                    else -> error("Unsupported tracking command")
                }
            }
            else -> error("Unexpected Bluetooth message")
        }
    }

    private val bondChanges = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val device = if (Build.VERSION.SDK_INT >= 33)
                intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                else intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE)
            if (!device?.address.equals(address, true)) return
            val state = intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, BluetoothDevice.ERROR)
            handler.post {
                if (closed) return@post
                when (state) {
                    BluetoothDevice.BOND_BONDED -> { if (flight == "bond") flight = null; retryAt = 0 }
                    BluetoothDevice.BOND_NONE -> fail("Bluetooth pairing ended. Disconnect to try again.", stop = true)
                }
            }
        }
    }
    private val callback = object : BluetoothGattCallback() {
        private fun current(value: BluetoothGatt, operation: String, block: () -> Unit) = handler.post {
            if (!closed && gatt === value) runCatching(block).onFailure {
                fail("Secure Bluetooth failed during $operation (${it.javaClass.simpleName})")
            }
        }
        override fun onConnectionStateChange(value: BluetoothGatt, status: Int, state: Int) { current(value, "connection") {
            if (status != BluetoothGatt.GATT_SUCCESS || state == BluetoothProfile.STATE_DISCONNECTED) fail("Bluetooth disconnected ($status)")
            else if (state == BluetoothProfile.STATE_CONNECTED) {
                begin("services")
                if (!value.discoverServices()) fail("Bluetooth service discovery failed")
            }
        } }
        override fun onServicesDiscovered(value: BluetoothGatt, status: Int) { current(value, "service discovery") {
            if (flight != "services") return@current
            val service = value.getService(BleProtocol.SERVICE)
            control = service?.getCharacteristic(BleProtocol.CONTROL)
            pose = service?.getCharacteristic(BleProtocol.POSE)
            if (status != 0 || control == null || pose == null) fail("FramePhone Bluetooth service unavailable")
            else {
                value.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
                begin("mtu"); if (!value.requestMtu(517)) flight = null
            }
        } }
        override fun onMtuChanged(value: BluetoothGatt, size: Int, status: Int) { current(value, "MTU negotiation") {
            if (status == 0) mtu = size.coerceIn(23, 517)
            if (flight == "mtu") flight = null
        } }
        private fun read(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, bytes: ByteArray, status: Int) { current(value, "TLS read") {
            if (characteristic.uuid != BleProtocol.CONTROL || flight != "read") return@current
            flight = null
            if (status != 0) fail("Bluetooth read failed ($status)")
            else {
                tls!!.receive(bytes).forEach { message(it) }
                flush()
                controlReads.completed(SystemClock.elapsedRealtime(), authenticated, standalone)
            }
        } }
        override fun onCharacteristicRead(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) =
            read(value, characteristic, characteristic.value ?: byteArrayOf(), status)
        override fun onCharacteristicRead(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, bytes: ByteArray, status: Int) =
            read(value, characteristic, bytes, status)
        override fun onCharacteristicWrite(value: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) { current(value, "Bluetooth write") {
            if (flight !in listOf("write", "pose")) return@current
            flight = null
            if (status != 0) fail("Bluetooth write failed ($status)")
        } }
    }
    private fun write(characteristic: BluetoothGattCharacteristic, bytes: ByteArray, response: Boolean): Boolean {
        val type = if (response) BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT else BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
        return if (Build.VERSION.SDK_INT >= 33) gatt!!.writeCharacteristic(characteristic, bytes, type) == BluetoothStatusCodes.SUCCESS
        else { characteristic.writeType = type; characteristic.value = bytes; gatt!!.writeCharacteristic(characteristic) }
    }
    private val tick = object : Runnable {
        override fun run() {
            if (closed) return
            var operation = "connection"
            runCatching {
                val now = SystemClock.elapsedRealtime()
                if (flight != null && now-flightAt > if (flight == "bond") 90000 else if (flight == "mtu") 2000 else 10000) {
                    if (flight == "mtu") flight = null else fail("Bluetooth connection timed out", stop = flight == "bond")
                }
                if (!blocked && gatt == null && flight == null && now >= retryAt) {
                    val adapter = context.getSystemService(BluetoothManager::class.java).adapter
                    if (adapter?.isEnabled == true) {
                        val device = adapter.getRemoteDevice(address)
                        if (device.bondState == BluetoothDevice.BOND_BONDED) {
                            begin("connect")
                            gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
                            BluetoothPose.status = "Bluetooth connecting"
                        } else {
                            begin("bond")
                            BluetoothPose.status = "Pairing over Bluetooth"
                            if (device.bondState == BluetoothDevice.BOND_NONE) {
                                store.resetApplicationTrust()
                                if (!device.createBond()) fail("Could not start Bluetooth pairing", stop = true)
                            }
                        }
                    } else retryAt = now+2000
                }
                operation = "TLS setup"
                if (control != null && tls == null && tlsContext != null) tls = BluetoothTls(tlsContext!!)
                if (flight == null && control != null && tls != null) {
                    val yieldedRead = controlReads.mustYield()
                    if (writes.isNotEmpty()) {
                        operation = "Bluetooth write"
                        begin("write")
                        if (!write(control!!, writes.removeFirst(), true)) fail("Bluetooth write busy")
                    } else if (!blocked && authenticated && sentHost != host) {
                        operation = "secure route update"
                        send(JSONObject().put("op", "route").put("host", host)); sentHost = host
                    } else if (!blocked && authenticated && session != null && !bound && now >= bindAt) {
                        operation = "secure session binding"
                        bindAt = now+500
                        send(JSONObject().put("op", "bind").put("session", session))
                    } else if (!blocked && controlReads.shouldRead(now)) {
                        operation = "Bluetooth read"
                        begin("read")
                        if (gatt?.readCharacteristic(control) != true) fail("Bluetooth read busy")
                    } else if (!blocked && standalone && bound && now >= markerAt) {
                        val marker = JSONObject().put("type", "marker_state").put("session", session)
                            .put("displayed", Fiducial.displayed)
                            .apply { runCatching { Fiducial.currentProfile(context) }.getOrNull()?.let { put("fiducial", it) } }
                        send(JSONObject().put("op", "tracking").put("message", marker))
                        markerAt = now+250
                    } else if (!blocked && standalone && bound && now >= sensorAt && feed != null) {
                        send(JSONObject().put("op", "tracking").put("message", feed!!.latestBatch(session!!)))
                        sensorAt = now+500
                    } else if (!blocked && isBound() && pose != null) {
                        operation = "pose encoding"
                        val value = session?.let(latest)
                        val encoded = value?.toString()
                        if (value != null && encoded != lastPose && value.getString("session") == session) {
                            tls!!.send(byteArrayOf(1)+BleProtocol.pose(value, BluetoothPose.samples(), maxOf(BleProtocol.POSE_BYTES, mtu-68)))
                            val bytes = tls!!.take()
                            if (bytes.size <= minOf(mtu-3, BleProtocol.MAX_ATTRIBUTE_BYTES)) {
                                begin("pose")
                                if (!write(pose!!, bytes, false)) fail("Bluetooth pose busy")
                            } else writes.addAll(BleProtocol.fragments(bytes, mtu, ++messageId))
                            lastPose = encoded!!
                        } else if (value != null && gyroStream && mtu >= BleProtocol.POSE_BYTES+68 && now >= gyroAt &&
                            value.optString("session") == session && value.optString("state") == "tracking" &&
                            !value.optBoolean("marker_required", true)) {
                            val sampleNow = SystemClock.elapsedRealtimeNanos()
                            val samples = BluetoothPose.samples().filter {
                                sampleNow-it.time in 0..30_000_000L
                            }
                            if (samples.isNotEmpty() && samples.last().time > lastGyro) {
                                operation = "gyro encoding"
                                tls!!.send(byteArrayOf(2)+BleProtocol.gyro(value, samples, mtu-68))
                                val bytes = tls!!.take()
                                if (bytes.size <= minOf(mtu-3, BleProtocol.MAX_ATTRIBUTE_BYTES)) {
                                    begin("pose")
                                    if (!write(pose!!, bytes, false)) fail("Bluetooth gyro busy")
                                } else writes.addAll(BleProtocol.fragments(bytes, mtu, ++messageId))
                                lastGyro = samples.last().time
                                gyroAt = now+10
                            }
                        }
                    }
                    if (yieldedRead) controlReads.outgoingTurn()
                }
            }.onFailure { fail("Secure Bluetooth failed during $operation (${it.javaClass.simpleName})") }
            handler.postDelayed(this, if (isBound() || writes.isNotEmpty()) 4 else 50)
        }
    }
    init {
        ContextCompat.registerReceiver(context, bondChanges, IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED), ContextCompat.RECEIVER_EXPORTED)
        handler.post(tick)
    }
    fun close() {
        closed = true
        handler.post {
            release()
            context.unregisterReceiver(bondChanges)
            handler.removeCallbacksAndMessages(null); worker.quitSafely()
        }
    }
}
