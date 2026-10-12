package com.example.framephone.overlay

import android.annotation.SuppressLint
import android.app.*
import android.content.*
import android.content.res.Configuration
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.os.*
import android.provider.Settings
import android.util.Log
import android.view.*
import androidx.core.content.ContextCompat
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.example.framephone.MainActivity
import com.example.framephone.SettingsStore
import com.example.framephone.geometry.*
import com.example.framephone.markers.Tag36h11
import java.util.UUID

data class OverlayStatus(val enabled: Boolean = false, val message: String = "Overlay off", val layout: LayoutExport? = null)

/** In-process UI state, deliberately not persisted: a dead service must never look enabled. */
object OverlayState {
    var status by mutableStateOf(OverlayStatus())
        internal set
}

class FiducialService : Service(), DisplayManager.DisplayListener {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var overlayContext: Context
    private lateinit var wm: WindowManager
    private lateinit var displays: DisplayManager
    private val views = mutableListOf<Pair<TagView, RenderedMarker>>()
    private var snapshot: DisplaySnapshot? = null
    private var calibration: ScreenCalibration? = null
    private var config = OverlayConfig()
    private var geometryPending = true
    private var layoutGeneration = 0
    private var updateRequestedNs = 0L
    private var lastRenderedRotation: Int? = null
    private var rotationWhiteOnly = false
    private val showRotationTags = Runnable {
        rotationWhiteOnly = false
        views.forEach { (view, _) -> view.setWhiteOnly(false) }
    }
    private val rebuild = Runnable { render() }
    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == Intent.ACTION_SCREEN_OFF) {
                handler.removeCallbacks(rebuild)
                clearViews()
                OverlayState.status = OverlayStatus(true, "Paused while display is off")
            } else schedule()
        }
    }

    override fun onCreate() {
        super.onCreate()
        displays = getSystemService(DisplayManager::class.java)
        val display = displays.getDisplay(Display.DEFAULT_DISPLAY)
        overlayContext = createDisplayContext(display).createWindowContext(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, null)
        wm = overlayContext.getSystemService(WindowManager::class.java)
        displays.registerDisplayListener(this, handler)
        ContextCompat.registerReceiver(this, screenReceiver, IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_USER_PRESENT)
        }, ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { stopSelf(); return START_NOT_STICKY }
        if (!Settings.canDrawOverlays(this)) {
            OverlayState.status = OverlayStatus(message = "Grant Display over other apps first")
            stopSelf()
            return START_NOT_STICKY
        }
        val notifications = getSystemService(NotificationManager::class.java)
        notifications.createNotificationChannel(NotificationChannel(CHANNEL, "Fiducial overlay", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(this, 0, Intent(this, FiducialService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_view).setContentTitle("Phone fiducials enabled")
            .setContentText("Tap to configure, or Stop to remove markers")
            .setContentIntent(open).setOngoing(true).setShowWhen(false)
            .addAction(Notification.Action.Builder(null, "Stop", stop).build()).build()
        startForeground(1, notification)
        handler.removeCallbacks(rebuild)
        updateRequestedNs = SystemClock.elapsedRealtimeNanos()
        render()
        return START_NOT_STICKY
    }

    private fun schedule() {
        // Coalesce callbacks already queued on the main looper, without waiting extra frames.
        if (!handler.hasCallbacks(rebuild)) updateRequestedNs = SystemClock.elapsedRealtimeNanos()
        hideForGeometryUpdate()
        layoutGeneration++
        OverlayState.status = OverlayState.status.copy(message = "Updating display geometry", layout = null)
        if (!handler.hasCallbacks(rebuild)) handler.post(rebuild)
    }

    private fun render() {
        val startedNs = SystemClock.elapsedRealtimeNanos()
        geometryPending = true
        OverlayState.status = OverlayState.status.copy(message = "Measuring marker windows", layout = null)
        if (!Settings.canDrawOverlays(this)) {
            clearViews()
            OverlayState.status = OverlayStatus(message = "Overlay permission was revoked")
            stopSelf()
            return
        }
        if (!getSystemService(PowerManager::class.java).isInteractive || getSystemService(KeyguardManager::class.java).isKeyguardLocked) {
            clearViews()
            OverlayState.status = OverlayStatus(true, "Paused until phone is unlocked")
            return
        }
        try {
            val display = displays.getDisplay(Display.DEFAULT_DISPLAY)
            val measured = DisplaySnapshot.read(overlayContext, display)
            val store = SettingsStore(this)
            val calibrated = store.calibration(measured.key)
                ?: throw IllegalArgumentException("Measure and save this display's physical dimensions first")
            val nextConfig = store.config()
            val geometryStartedNs = SystemClock.elapsedRealtimeNanos()
            val markers = MarkerGeometry.layout(measured.geometry(calibrated), measured.rotationStableMarkerBounds(), nextConfig)
            val geometryFinishedNs = SystemClock.elapsedRealtimeNanos()
            reconcileWindows(measured, calibrated, nextConfig, markers)
            val finishedNs = SystemClock.elapsedRealtimeNanos()
            Log.d(TIMING_TAG, "rotation=${measured.rotation} queueUs=${(startedNs - updateRequestedNs) / 1000} " +
                "snapshotSettingsUs=${(geometryStartedNs - startedNs) / 1000} " +
                "geometryUs=${(geometryFinishedNs - geometryStartedNs) / 1000} " +
                "windowsUs=${(finishedNs - geometryFinishedNs) / 1000} " +
                "frameBudgetUs=${(1_000_000.0 / display.refreshRate).toLong()}")
        } catch (e: IllegalArgumentException) {
            clearViews()
            OverlayState.status = OverlayStatus(true, e.message ?: "Invalid geometry")
        } catch (e: SecurityException) {
            clearViews()
            OverlayState.status = OverlayStatus(message = "Android denied overlay access: ${e.message}")
            stopSelf()
        } catch (e: WindowManager.BadTokenException) {
            clearViews()
            OverlayState.status = OverlayStatus(message = "Android could not attach overlay windows")
            stopSelf()
        }
    }

    private fun reconcileWindows(
        measured: DisplaySnapshot,
        calibrated: ScreenCalibration,
        nextConfig: OverlayConfig,
        markers: List<RenderedMarker>,
    ) {
        val rotationChanged = lastRenderedRotation?.let { it != measured.rotation } ?: false
        if (rotationChanged) {
            rotationWhiteOnly = true
            views.forEach { (view, _) -> view.setWhiteOnly(true) }
            handler.removeCallbacks(showRotationTags)
            handler.postDelayed(showRotationTags, ROTATION_WHITE_DURATION_MS)
        }
        lastRenderedRotation = measured.rotation
        // The service can also be restarted by the activity during rotation, bypassing schedule().
        // Catch changed target bounds here before updating any attached window.
        val targetChanged = snapshot?.let { old ->
            old.rotation != measured.rotation || old.logicalWidthPx != measured.logicalWidthPx ||
                old.logicalHeightPx != measured.logicalHeightPx ||
                views.map { it.second } != markers
        } ?: false
        if (targetChanged) hideForGeometryUpdate()
        val existing = views.associateBy { it.second.id }
        val next = mutableListOf<Pair<TagView, RenderedMarker>>()
        snapshot = measured
        calibration = calibrated
        config = nextConfig
        for (marker in markers) {
            val previous = existing[marker.id]
            val view = previous?.first ?: TagView(overlayContext, marker, updateRequestedNs).also { newView ->
                newView.alpha = 0f
                newView.setWhiteOnly(rotationWhiteOnly)
                newView.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> publishMeasuredLayout() }
                // Post out of drawing traversal; export only after every tag has drawn.
                newView.onMarkerDrawn = { handler.post { publishMeasuredLayout() } }
                newView.setOnApplyWindowInsetsListener { _, insets ->
                    refreshInsetsSnapshot()
                    insets
                }
                wm.addView(newView, windowParams(marker))
                views += newView to marker
            }
            if (previous != null && previous.second != marker) {
                view.updateMarker(marker, updateRequestedNs)
                if (previous.second.bounds != marker.bounds) wm.updateViewLayout(view, windowParams(marker))
            }
            next += view to marker
        }
        views.filter { current -> next.none { it.first === current.first } }.toList().forEach { obsolete ->
            wm.removeViewImmediate(obsolete.first)
        }
        views.clear()
        views.addAll(next)
        layoutGeneration++
        geometryPending = false
        handler.post { publishMeasuredLayout() }
    }

    private fun refreshInsetsSnapshot() {
        val previous = snapshot ?: return
        val display = displays.getDisplay(Display.DEFAULT_DISPLAY) ?: return
        val latest = DisplaySnapshot.read(overlayContext, display)
        if (latest == previous) return
        val needsRelayout = geometryChanged(previous, latest)
        snapshot = latest
        if (needsRelayout) schedule() else if (!geometryPending) publishMeasuredLayout()
    }

    private fun geometryChanged(old: DisplaySnapshot, new: DisplaySnapshot) =
        old.key != new.key || old.rotation != new.rotation ||
            old.logicalWidthPx != new.logicalWidthPx || old.logicalHeightPx != new.logicalHeightPx ||
            old.roundedCornerRadiusPx != new.roundedCornerRadiusPx || old.cutouts != new.cutouts

    private fun scheduleIfDisplayGeometryChanged() {
        val latest = displays.getDisplay(Display.DEFAULT_DISPLAY)?.let { DisplaySnapshot.read(overlayContext, it) }
            ?: return
        val previous = snapshot
        if (previous == null || geometryChanged(previous, latest)) {
            schedule()
        } else if (latest != previous) {
            snapshot = latest // Insets/DPI diagnostics changed; marker coordinates did not.
            if (!geometryPending) publishMeasuredLayout()
        }
    }

    private fun hideForGeometryUpdate() {
        views.filter { (view, _) -> view.alpha != 0f }.forEach { (view, _) -> view.alpha = 0f }
        geometryPending = true
    }

    @SuppressLint("RtlHardcoded") // Physical pixel coordinates must not mirror in RTL locales.
    private fun windowParams(marker: RenderedMarker) = WindowManager.LayoutParams(
        marker.bounds.width, marker.bounds.height, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
        PixelFormat.OPAQUE,
    ).apply {
        gravity = Gravity.TOP or Gravity.LEFT
        x = marker.bounds.left
        y = marker.bounds.top
        setFitInsetsTypes(0)
        layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
        windowAnimations = android.R.style.Animation // Framework base animation style contains no transitions.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            setCanPlayMoveAnimation(false)
        }
        title = "Phone tag ${marker.id}"
    }

    private fun publishMeasuredLayout() {
        if (geometryPending) return
        val display = snapshot ?: return
        val calibrated = calibration ?: return
        val expectedCount = config.layout.ids.size
        if (views.size != expectedCount || views.any { (view, marker) ->
                !view.isLaidOut || !view.hasDrawn(marker) ||
                    view.width != marker.bounds.width || view.height != marker.bounds.height
            }) return
        try {
            val actual = views.map { (view, marker) ->
                val location = IntArray(2).also(view::getLocationOnScreen)
                marker.copy(bounds = PixelRect(location[0], location[1], location[0] + view.width, location[1] + view.height))
            }
            // A layout/draw callback can arrive before another window finishes repositioning.
            if (actual.zip(views).any { (marker, expected) -> marker.bounds != expected.second.bounds }) return
            MarkerGeometry.validate(actual, display.rotationStableMarkerBounds())
            require(actual.none { marker -> display.cutouts.any { it.intersects(marker.bounds) } }) { "Marker intersects display cutout" }
            views.forEach { (view, _) -> view.alpha = 1f }
            OverlayState.status = OverlayStatus(true, "${actual.size} markers active · manually calibrated",
                LayoutExport(display, calibrated, config, actual, SystemClock.elapsedRealtimeNanos(), UUID.randomUUID().toString()))
        } catch (e: IllegalArgumentException) {
            // Removal is posted because this callback runs during ViewRoot's layout traversal.
            OverlayState.status = OverlayStatus(true, e.message ?: "Invalid rendered geometry")
            val generation = layoutGeneration
            handler.post { if (generation == layoutGeneration) clearViews() }
        }
    }

    private fun clearViews() {
        layoutGeneration++
        handler.removeCallbacks(showRotationTags)
        rotationWhiteOnly = false
        lastRenderedRotation = null
        views.forEach { (view, _) -> wm.removeViewImmediate(view) }
        views.clear()
        snapshot = null
        calibration = null
        geometryPending = true
        OverlayState.status = OverlayState.status.copy(layout = null)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        scheduleIfDisplayGeometryChanged()
    }
    override fun onDisplayAdded(displayId: Int) = Unit
    override fun onDisplayRemoved(displayId: Int) { if (displayId == Display.DEFAULT_DISPLAY) stopSelf() }
    override fun onDisplayChanged(displayId: Int) {
        if (displayId == Display.DEFAULT_DISPLAY) scheduleIfDisplayGeometryChanged()
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        clearViews()
        displays.unregisterDisplayListener(this)
        unregisterReceiver(screenReceiver)
        stopForeground(STOP_FOREGROUND_REMOVE)
        OverlayState.status = OverlayStatus()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "fiducial_overlay"
        private const val ACTION_STOP = "com.example.framephone.STOP"
        private const val ROTATION_WHITE_DURATION_MS = 200L
    }
}

private const val TIMING_TAG = "FiducialTiming"

/** No animation, bitmap resampling, antialiasing, sensors, polling, or wakelock. */
@SuppressLint("ViewConstructor") // Created programmatically with required, verified tag geometry.
private class TagView(context: Context, marker: RenderedMarker, requestedNs: Long) : View(context) {
    // Prepare all raster orientations once per attached tag, outside subsequent rotation updates.
    private val rasters: Array<BooleanArray> = Array(4) { rotateCells(Tag36h11.cells(marker.id), it) }
    private var currentMarker = marker
    private var drawnMarker: RenderedMarker? = null
    private var drawRequestedNs = requestedNs
    private var whiteOnly = false
    private var cells: BooleanArray = rasters[marker.imageRotationQuarterTurns]
    private var cw = marker.cellWidthPx
    private var ch = marker.cellHeightPx
    private val paint = Paint().apply { color = Color.BLACK; isAntiAlias = false; isFilterBitmap = false }
    init { importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO }

    var onMarkerDrawn: (() -> Unit)? = null

    fun hasDrawn(marker: RenderedMarker) = !whiteOnly && drawnMarker == marker

    fun setWhiteOnly(enabled: Boolean) {
        if (whiteOnly != enabled) {
            whiteOnly = enabled
            drawnMarker = null
            invalidate()
        }
    }

    fun updateMarker(marker: RenderedMarker, requestedNs: Long) {
        currentMarker = marker
        drawnMarker = null
        drawRequestedNs = requestedNs
        cells = rasters[marker.imageRotationQuarterTurns]
        cw = marker.cellWidthPx
        ch = marker.cellHeightPx
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val startedNs = SystemClock.elapsedRealtimeNanos()
        canvas.drawColor(Color.WHITE)
        if (!whiteOnly) {
            for (y in 0..9) for (x in 0..9) if (!cells[y * 10 + x]) {
                canvas.drawRect((x * cw).toFloat(), (y * ch).toFloat(), ((x + 1) * cw).toFloat(), ((y + 1) * ch).toFloat(), paint)
            }
        }
        if (!whiteOnly && drawnMarker != currentMarker) {
            val finishedNs = SystemClock.elapsedRealtimeNanos()
            drawnMarker = currentMarker
            Log.d(TIMING_TAG, "tag=${currentMarker.id} drawCpuUs=${(finishedNs - startedNs) / 1000} " +
                "callbackToDrawUs=${(finishedNs - drawRequestedNs) / 1000}")
        }
        onMarkerDrawn?.invoke()
    }

    private fun rotateCells(source: BooleanArray, clockwiseTurns: Int): BooleanArray {
        var result = source
        repeat(clockwiseTurns) {
            val rotated = BooleanArray(100)
            for (row in 0..9) for (column in 0..9) {
                rotated[column * 10 + (9 - row)] = result[row * 10 + column]
            }
            result = rotated
        }
        return result
    }
}
