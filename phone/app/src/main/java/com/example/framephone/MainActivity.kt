package com.example.framephone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color as AndroidColor
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import com.example.framephone.geometry.*
import com.example.framephone.overlay.FiducialService
import com.example.framephone.overlay.OverlayState
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {
    private lateinit var store: SettingsStore
    private var displayInfo by mutableStateOf<DisplaySnapshot?>(null)
    private var notice by mutableStateOf("")
    private var permission by mutableStateOf(false)
    private var calibrationVersion by mutableIntStateOf(0)
    private var pendingExport: String? = null
    private val notifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        notice = if (granted) "Notification enabled" else "Notifications denied; overlay can still be stopped from this app or Android's active-app controls"
        startOverlay()
    }
    private val exportDocument = registerForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        val content = pendingExport
        pendingExport = null
        if (uri != null && content != null) thread(name = "layout-export") {
            val result = runCatching {
                val stream = contentResolver.openOutputStream(uri, "wt") ?: error("Cannot open destination")
                stream.bufferedWriter(Charsets.UTF_8).use { it.write(content) }
            }
            runOnUiThread { notice = result.fold({ "Saved measured layout snapshot" }, { "Export failed: ${it.message}" }) }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = SettingsStore(this)
        pendingExport = savedInstanceState?.getString("pending_export")
        window.decorView.setBackgroundColor(AndroidColor.WHITE)
        refreshDisplay()
        setContent { MaterialTheme { ConfigurationScreen() } }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("pending_export", pendingExport)
        super.onSaveInstanceState(outState)
    }

    override fun onResume() {
        super.onResume()
        permission = Settings.canDrawOverlays(this)
        refreshDisplay()
        if (OverlayState.status.enabled) startOverlay()
    }

    private fun refreshDisplay() {
        runCatching {
            val current = display ?: error("Display unavailable")
            val context = createDisplayContext(current).createWindowContext(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, null)
            DisplaySnapshot.read(context, current)
        }.onSuccess { displayInfo = it }.onFailure { notice = "Display unavailable: ${it.message}" }
    }

    private fun startOverlay() {
        runCatching { startForegroundService(Intent(this, FiducialService::class.java)) }
            .onFailure { notice = "Cannot start overlay: ${it.message}" }
    }

    private fun applyConfig(config: OverlayConfig) {
        store.save(config)
        if (OverlayState.status.enabled) startOverlay()
    }

    @Composable
    private fun ConfigurationScreen() {
        val display = displayInfo
        var config by remember { mutableStateOf(store.config()) }
        val calibration = remember(display?.key, calibrationVersion) { display?.let { store.calibration(it.key) } }
        var width by remember(display?.key, calibrationVersion) { mutableStateOf(calibration?.let { "%.2f".format(java.util.Locale.US, it.portraitWidthM * 1000) } ?: "") }
        var height by remember(display?.key, calibrationVersion) { mutableStateOf(calibration?.let { "%.2f".format(java.util.Locale.US, it.portraitHeightM * 1000) } ?: "") }
        val status = OverlayState.status
        var showRuler by remember { mutableStateOf(false) }
        if (showRuler && display != null && calibration != null) {
            CalibrationRuler(display.geometry(calibration)) { showRuler = false }
        }
        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).safeDrawingPadding()
            .verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Frame Fiducials", style = MaterialTheme.typography.headlineMedium)
            Text("Optical tracking experiment · tag36h11 fiducials")
            Text(status.message)
            if (notice.isNotEmpty()) Text(notice, color = MaterialTheme.colorScheme.primary)
            Button(onClick = {
                if (status.enabled) stopService(Intent(this@MainActivity, FiducialService::class.java))
                else if (!permission) {
                    runCatching { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, "package:$packageName".toUri())) }
                        .onFailure { notice = "Overlay settings unavailable: ${it.message}" }
                } else if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                } else startOverlay()
            }, enabled = status.enabled || calibration != null || !permission) {
                Text(if (status.enabled) "Disable overlay" else if (!permission) "Grant overlay permission" else "Enable overlay")
            }
            Text("Markers stay at the same phone-frame positions through screen rotation and may sit in system-bar areas. They cover small touch regions. Apps with protected windows can hide overlays. Stop the overlay to reach covered controls.")
            HorizontalDivider()
            Text("Physical screen calibration", style = MaterialTheme.typography.titleLarge)
            Text("Manual measurement only: use a ruler to measure the illuminated panel edge to edge in portrait, excluding bezel and glass. Include areas behind system bars. Recalibrate after changing display resolution or folding the device.")
            OutlinedTextField(width, { width = it }, label = { Text("Portrait active width (mm)") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(height, { height = it }, label = { Text("Portrait active height (mm)") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
            Button(onClick = {
                runCatching {
                    val info = display ?: error("Display unavailable")
                    store.save(ScreenCalibration(info.key, width.replace(',', '.').toDouble() / 1000,
                        height.replace(',', '.').toDouble() / 1000, System.currentTimeMillis()))
                    calibrationVersion++
                    notice = "Manual calibration saved for this display configuration"
                    if (status.enabled) startOverlay()
                }.onFailure { notice = "Enter valid measured dimensions: width 20–500 mm, height at least width and at most 800 mm" }
            }, enabled = display != null) { Text("Save calibration") }
            Text(if (calibration == null) "UNCALIBRATED — physical overlay and export disabled" else "MANUAL MEASUREMENT — camera accuracy remains unverified")
            Button(onClick = { showRuler = true }, enabled = calibration != null && display != null && !status.enabled) {
                Text("High-contrast calibration ruler")
            }
            Text("Disable the overlay to check the 50 mm ruler against a physical ruler. Correct the active display measurements if it differs.")
            HorizontalDivider()
            Text("Marker layout", style = MaterialTheme.typography.titleLarge)
            MarkerLayout.entries.forEach { layout ->
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    RadioButton(config.layout == layout, onClick = { config = config.copy(layout = layout); applyConfig(config) })
                    Text(layout.label)
                }
            }
            Text("Detector boundary size: ${config.markerSizeMm.toInt()} mm")
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf(8.0, 12.0, 16.0, 20.0).forEach { mm ->
                    FilterChip(config.markerSizeMm == mm, { config = config.copy(markerSizeMm = mm); applyConfig(config) }, label = { Text("${mm.toInt()}") })
                }
            }
            Text("White quiet zone adds 25% to each marker's total width and height. Export contains actual sizes after pixel rounding.")
            Text("Margin beyond quiet zone: ${config.marginMm.toInt()} mm")
            Slider(config.marginMm.toFloat(), { config = config.copy(marginMm = it.toDouble()) },
                onValueChangeFinished = { applyConfig(config) }, valueRange = 0f..20f, steps = 19)
            Text("Display orientation")
            OrientationPolicy.entries.forEach { policy ->
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    RadioButton(config.orientation == policy, onClick = { config = config.copy(orientation = policy); applyConfig(config) })
                    Text(when (policy) {
                        OrientationPolicy.FOLLOW_DISPLAY -> "Keep fiducials fixed on phone as display rotates"
                        OrientationPolicy.PORTRAIT_ONLY -> "Portrait only (pause in landscape)"
                        OrientationPolicy.LANDSCAPE_ONLY -> "Landscape only (pause in portrait)"
                    })
                }
            }
            HorizontalDivider()
            Text("Diagnostics", style = MaterialTheme.typography.titleLarge)
            if (display != null) Text(
                "Display ${display.displayId}: ${display.displayName}\n" +
                    "Reported physical mode: ${display.physicalWidthPx} × ${display.physicalHeightPx} px\n" +
                    "Logical display: ${display.logicalWidthPx} × ${display.logicalHeightPx} px\n" +
                    "Surface rotation: ${display.rotation * 90}°; natural portrait: ${display.naturalPortrait}\n" +
                    "Reported DPI (untrusted): ${display.xdpi} × ${display.ydpi}; density: ${display.densityDpi}\n" +
                    "Insets L/T/R/B: ${display.insets}\nUsable: ${display.usable}\nCutouts: ${display.cutouts}\n" +
                    "Rounded corner clearance: ${display.roundedCornerRadiusPx} px",
            )
            status.layout?.let { measured ->
                measured.markers.forEach { marker -> Text("ID ${marker.id}: ${marker.bounds}\nCorners (m): ${marker.cornersM(measured.display.geometry(measured.calibration))}") }
            }
            Button(onClick = {
                runCatching {
                    pendingExport = requireNotNull(OverlayState.status.layout) { "Wait for rendered marker geometry" }.json()
                    exportDocument.launch("phone-layout-v1.json")
                }.onFailure { notice = "Cannot export: ${it.message}" }
            }, enabled = status.layout != null) { Text("Export measured layout JSON") }
            Text("Export is a snapshot. Export again after rotation, calibration, layout, or display changes. No camera or network data is collected.")
        }
    }

}
