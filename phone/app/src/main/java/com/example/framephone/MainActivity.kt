package com.example.framephone

import com.example.framephone.bluetooth.BluetoothPose
import com.example.framephone.bluetooth.CompanionSetup
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanResult
import android.companion.CompanionDeviceManager
import androidx.activity.result.IntentSenderRequest
import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.example.framephone.link.PhoneDimensions
import com.example.framephone.link.TelemetryService
import com.example.framephone.link.TelemetryState
import com.example.framephone.tracking.ArPoseService
import com.example.framephone.tracking.ArPoseState
import com.google.ar.core.ArCoreApk
import kotlinx.coroutines.delay

class MainActivity : ComponentActivity() {
    private lateinit var store: SettingsStore
    private var notice by mutableStateOf("")
    private var connectionDetail by mutableStateOf("")
    private var pendingConnect = false
    private var waiting = ""
    private var installRequested = false
    private var notificationsAsked = false
    private val bluetoothPermission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        waiting = ""
        if (granted.values.all { it }) continueConnection()
        else { pendingConnect = false; notice = "Bluetooth access is required for automatic connection." }
    }
    @Suppress("DEPRECATION")
    private val companionPicker = registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { result ->
        if (result.resultCode != RESULT_OK) {
            waiting = ""; pendingConnect = false; notice = "Bluetooth selection cancelled."
        } else {
            val association = if (Build.VERSION.SDK_INT >= 33)
                result.data?.getParcelableExtra(CompanionDeviceManager.EXTRA_ASSOCIATION, android.companion.AssociationInfo::class.java)
                else null
            val value = result.data?.getParcelableExtra<android.os.Parcelable>(CompanionDeviceManager.EXTRA_DEVICE)
            val address = association?.deviceMacAddress?.toString() ?: when (value) {
                is ScanResult -> value.device.address
                is BluetoothDevice -> value.address
                else -> null
            }
            if (address != null) bluetoothSelected(address, association?.id ?: -1)
        }
    }
    private fun bluetoothSelected(address: String, id: Int) {
        runCatching { CompanionSetup.remember(this, address, id) }.onFailure {
            pendingConnect = false; notice = "Bluetooth setup failed: ${it.javaClass.simpleName}"
        }.onSuccess {
            waiting = ""
            if (lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED)) continueConnection()
        }
    }
    private val notifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        waiting = ""
        continueConnection()
    }
    private val camera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        waiting = ""
        if (granted) continueConnection() else { pendingConnect = false; notice = "Camera access is required." }
    }
    private val overlayAccess = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        waiting = ""
        if (pendingConnect) {
            if (Settings.canDrawOverlays(this)) continueConnection()
            else { pendingConnect = false; notice = "Allow display over other apps to connect." }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = SettingsStore(this)
        pendingConnect = savedInstanceState?.getBoolean("pending_connect") ?: false
        waiting = savedInstanceState?.getString("waiting").orEmpty()
        installRequested = savedInstanceState?.getBoolean("install_requested") ?: false
        notificationsAsked = savedInstanceState?.getBoolean("notifications_asked") ?: false
        setContent {
            MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()) {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { Screen() }
            }
        }
    }
    override fun onResume() {
        super.onResume()
        if (pendingConnect && waiting in listOf("", "arcore")) continueConnection()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("pending_connect", pendingConnect)
        outState.putString("waiting", waiting)
        outState.putBoolean("install_requested", installRequested)
        outState.putBoolean("notifications_asked", notificationsAsked)
        super.onSaveInstanceState(outState)
    }

    private fun command(action: String) {
        runCatching {
            startService(Intent(this, TelemetryService::class.java).setAction(action))
        }.onFailure { notice = "Connection action failed." }
    }
    private fun connect() {
        notice = ""; connectionDetail = ""; pendingConnect = true; continueConnection()
    }
    private fun continueConnection() {
        if (!pendingConnect) return
        try {
            if (Build.VERSION.SDK_INT >= 33 && !notificationsAsked &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                notificationsAsked = true
                waiting = "notifications"
                notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                return
            }
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                waiting = "camera"
                camera.launch(Manifest.permission.CAMERA)
                return
            }
            if (!Settings.canDrawOverlays(this)) {
                waiting = "overlay"
                overlayAccess.launch(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
                return
            }
            run {
                val requiredBluetooth = arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
                if (requiredBluetooth.any { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }) {
                    waiting = "bluetooth_permissions"; bluetoothPermission.launch(requiredBluetooth); return
                }
                if (getSystemService(BluetoothManager::class.java).adapter?.isEnabled != true) {
                    pendingConnect = false; notice = "Enable Bluetooth on the phone and headset."; return
                }
                if (!CompanionSetup.associated(this)) {
                    waiting = "bluetooth_picker"
                    CompanionSetup.associate(this, { companionPicker.launch(IntentSenderRequest.Builder(it).build()) },
                        { info -> info.deviceMacAddress?.toString()?.let { bluetoothSelected(it, info.id) } },
                        { error -> waiting = ""; pendingConnect = false; notice = error })
                    return
                }
                CompanionSetup.observe(this)
            }
            waiting = "arcore"
            if (ArCoreApk.getInstance().requestInstall(this, !installRequested) == ArCoreApk.InstallStatus.INSTALL_REQUESTED) {
                installRequested = true
                return
            }
            waiting = ""
            pendingConnect = false
            // Arm camera access while visible. The worker opens the camera only
            // after authentication; reconnects never try to launch an activity.
            startForegroundService(Intent(this, ArPoseService::class.java).setAction("realign"))
            startForegroundService(Intent(this, TelemetryService::class.java).setAction("start"))
        } catch (error: Exception) {
            pendingConnect = false
            waiting = ""
            stopService(Intent(this, ArPoseService::class.java))
            notice = "Unable to start tracking. See Details."
            connectionDetail = "${error.javaClass.simpleName}: ${error.message.orEmpty()}"
        }
    }
    private fun openLink(url: String) = startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))

    @Composable
    private fun Screen() {
        val saved = remember { store.dimensions() }
        var width by rememberSaveable { mutableStateOf(saved?.widthMm?.toString().orEmpty()) }
        var height by rememberSaveable { mutableStateOf(saved?.heightMm?.toString().orEmpty()) }
        var details by rememberSaveable { mutableStateOf(false) }
        var about by remember { mutableStateOf(false) }
        var tracking by remember { mutableStateOf(ArPoseState.status) }
        var trackingDetail by remember { mutableStateOf("") }
        var trackingReady by remember { mutableStateOf(false) }
        var timedOut by remember { mutableStateOf(false) }
        var bluetoothStatus by remember { mutableStateOf(BluetoothPose.status) }
        var overlayAllowed by remember { mutableStateOf(Settings.canDrawOverlays(this)) }
        LaunchedEffect(Unit) {
            while (true) {
                tracking = ArPoseState.status
                bluetoothStatus = BluetoothPose.status
                trackingDetail = ArPoseState.detail
                trackingReady = ArPoseState.running && !ArPoseState.failed
                timedOut = ArPoseState.overlayTimedOut
                overlayAllowed = Settings.canDrawOverlays(this@MainActivity)
                delay(250)
            }
        }
        val status = TelemetryState.status
        var remembered by remember { mutableStateOf(store.pairedName()) }
        LaunchedEffect(status) { remembered = store.pairedName() }
        Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text("FramePhone", style = MaterialTheme.typography.headlineLarge)
            Text(when {
                !status.running -> if (status.message == "Stopped") "Ready to pair" else status.message
                !status.connected -> status.message
                timedOut -> "Alignment timed out"
                !trackingReady -> "Tracking unavailable"
                else -> tracking
            }, style = MaterialTheme.typography.titleMedium)
            Text(bluetoothStatus, style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                DimensionField("Width (mm)", width, !status.running, Modifier.weight(1f)) { width = it }
                DimensionField("Height (mm)", height, !status.running, Modifier.weight(1f)) { height = it }
            }
            Button(onClick = {
                if (status.running) command("stop") else {
                    runCatching { store.save(PhoneDimensions(width.replace(',', '.').toDouble(), height.replace(',', '.').toDouble())) }
                        .onSuccess { connect() }.onFailure { notice = "Enter a valid width and height." }
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(if (status.running) "Disconnect" else if (store.bluetoothAddress() == null) "Pair headset" else "Connect") }
            if (notice.isNotEmpty()) Text(notice, color = MaterialTheme.colorScheme.error)
            if (status.running && !overlayAllowed) {
                TextButton(onClick = {
                    overlayAccess.launch(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
                }) { Text("Allow overlay") }
            }
            if (status.running && (!trackingReady || timedOut)) {
                TextButton(onClick = { connect() }) { Text("Retry tracking") }
            }
            TextButton(onClick = { details = !details }) { Text(if (details) "Hide details" else "Details") }
            if (details) {
                Text(status.message)
                if (status.address.isNotEmpty()) Text("IP: ${status.address}")
                remembered?.let { Text("Headset: $it") }
                if (connectionDetail.isNotEmpty()) Text(connectionDetail)
                if (trackingDetail.isNotEmpty()) Text(trackingDetail)
                if (remembered != null) TextButton(onClick = { command("forget") }) { Text("Forget headset") }
                TextButton(onClick = { about = true }) { Text("About") }
            }
        }
        if (about) AlertDialog(onDismissRequest = { about = false }, title = { Text("FramePhone") },
            text = { Column {
                Text("Tracking uses Google ARCore, subject to Google's Terms of Service and Privacy Policy.")
                TextButton(onClick = { openLink("https://policies.google.com/terms") }) { Text("Google terms") }
                TextButton(onClick = { openLink("https://policies.google.com/privacy") }) { Text("Privacy policy") }
            } }, confirmButton = { TextButton(onClick = { about = false }) { Text("Close") } })
    }
}

@Composable
private fun DimensionField(label: String, value: String, enabled: Boolean, modifier: Modifier, change: (String) -> Unit) {
    OutlinedTextField(value, change, label = { Text(label) }, enabled = enabled, singleLine = true,
        colors = OutlinedTextFieldDefaults.colors(disabledTextColor = MaterialTheme.colorScheme.onSurface,
            disabledLabelColor = MaterialTheme.colorScheme.onSurfaceVariant),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = modifier)
}
