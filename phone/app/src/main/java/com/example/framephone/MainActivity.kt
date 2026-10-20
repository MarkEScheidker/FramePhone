package com.example.framephone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.example.framephone.link.PhoneDimensions
import com.example.framephone.link.TelemetryService
import com.example.framephone.link.TelemetryState

class MainActivity : ComponentActivity() {
    private lateinit var store: SettingsStore
    private var notice by mutableStateOf("")
    private var photoReady by mutableStateOf(false)
    private var photoLoading by mutableStateOf(false)
    private val photoPicker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            photoLoading = true
            kotlin.concurrent.thread(name = "photo-decode") {
                val selected = runCatching { PhotoReference.select(this, uri) }
                runOnUiThread {
                    photoLoading = false
                    selected.onSuccess {
                        photoReady = true
                        notice = ""
                        if (!isFinishing && !isDestroyed) startActivity(Intent(this, PhotoActivity::class.java))
                    }.onFailure { notice = it.message ?: "Unable to open photo" }
                }
            }
        }
    }
    private val notifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        startLink()
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = SettingsStore(this)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContent {
            val colors = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()
            MaterialTheme(colorScheme = colors) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                    contentColor = MaterialTheme.colorScheme.onBackground,
                ) { Screen() }
            }
        }
    }
    private fun command(action: String, request: String? = null) {
        runCatching {
            startService(Intent(this, TelemetryService::class.java).setAction(action).putExtra("request", request))
        }.onFailure { notice = "Unable to change connection: ${it.message}" }
    }
    private fun startLink() {
        runCatching { startForegroundService(Intent(this, TelemetryService::class.java).setAction("start")) }
            .onFailure { notice = "Unable to start: ${it.message}" }
    }
    @Composable
    private fun Screen() {
        val saved = remember { store.dimensions() }
        var width by rememberSaveable { mutableStateOf(saved?.widthMm?.toString() ?: "") }
        var height by rememberSaveable { mutableStateOf(saved?.heightMm?.toString() ?: "") }
        var thickness by rememberSaveable { mutableStateOf(saved?.thicknessMm?.toString() ?: "") }
        var remembered by remember { mutableStateOf(store.pairedName()) }
        val status = TelemetryState.status
        LaunchedEffect(status) { remembered = store.pairedName() }
        Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("FramePhone", style = MaterialTheme.typography.headlineLarge)
            Text("Phone dimensions and live motion sensors")
            Text("Measure the outside of the phone, including its case, in portrait. These are body dimensions, not the illuminated screen.")
            DimensionField("Width (mm)", width, !status.running) { width = it }
            DimensionField("Height (mm)", height, !status.running) { height = it }
            DimensionField("Thickness (mm)", thickness, !status.running) { thickness = it }
            Button(onClick = { photoPicker.launch("image/*") }, enabled = !photoLoading,
                modifier = Modifier.fillMaxWidth()) { Text(if (photoLoading) "Preparing photo…" else "Choose tracking photo") }
            if (photoReady || PhotoReference.current != null) OutlinedButton(
                onClick = { startActivity(Intent(this@MainActivity, PhotoActivity::class.java)) },
                modifier = Modifier.fillMaxWidth()) { Text("Show tracking photo (tap photo to return)") }
            Text("Choose a detailed photo. Frame downloads it once over the paired link and estimates its position and angle using the two front cameras. No screen recording or marker is needed.")
            Button(onClick = {
                runCatching {
                    store.save(PhoneDimensions(width.replace(',', '.').toDouble(),
                        height.replace(',', '.').toDouble(), thickness.replace(',', '.').toDouble()))
                    notice = ""
                    if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                        notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                    else startLink()
                }.onFailure { notice = "Enter width 20–500 mm, height between width and 800 mm, thickness 1–100 mm." }
            }, enabled = !status.running, modifier = Modifier.fillMaxWidth()) {
                Text(if (remembered == null) "Save dimensions and start pairing" else "Save dimensions and start connection")
            }
            if (notice.isNotEmpty()) Text(notice, color = MaterialTheme.colorScheme.error)
            HorizontalDivider()
            Text(status.message, style = MaterialTheme.typography.titleMedium)
            remembered?.let { Text("Remembered headset: $it") }
            if (status.running) {
                Text("Use the same LAN on both devices. On Frame, open Phone telemetry and choose Find phones.")
                if (status.address.isNotEmpty()) Text("Phone IP: ${status.address}")
                if (status.fingerprint.isNotEmpty()) {
                    Text("Pairing fingerprint (this connection)")
                    Text(status.fingerprint, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.titleLarge)
                }
                status.request?.let { request ->
                    Text("Pair with ${status.peer}? Verify all four groups match the Frame screen before approving.")
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Button(onClick = { command("approve", request) }) { Text("Fingerprints match") }
                        OutlinedButton(onClick = { command("reject", request) }) { Text("Reject") }
                    }
                }
                if (status.request == null) OutlinedButton(onClick = { command("pair") }) { Text("Pair new headset") }
                Button(onClick = { command("stop") }, modifier = Modifier.fillMaxWidth()) { Text("Stop connection") }
            }
            if (remembered != null) OutlinedButton(onClick = {
                command("forget"); remembered = null
            }) { Text("Forget headset and stop") }
            Text("Gyroscope and accelerometer request 200 Hz; magnetometer requests 50 Hz where available. Photo pose uses stereo camera measurements; ARCore alignment is a later step.")
            Text("Sensors use Android's fixed natural-device axes: X right, Y up, Z out of the screen. Rotating the UI does not rotate these axes. Stop the connection before editing dimensions.")
        }
    }
}

@Composable
private fun DimensionField(label: String, value: String, enabled: Boolean, change: (String) -> Unit) {
    OutlinedTextField(value, change, label = { Text(label) }, enabled = enabled, singleLine = true,
        colors = OutlinedTextFieldDefaults.colors(
            disabledTextColor = MaterialTheme.colorScheme.onSurface,
            disabledLabelColor = MaterialTheme.colorScheme.onSurfaceVariant,
        ),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
}
