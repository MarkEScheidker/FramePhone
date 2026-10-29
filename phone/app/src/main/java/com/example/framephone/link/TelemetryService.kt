package com.example.framephone.link

import com.example.framephone.bluetooth.BluetoothPose
import com.example.framephone.bluetooth.CompanionSetup
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.example.framephone.MainActivity
import com.example.framephone.SettingsStore
import com.example.framephone.tracking.ArPoseService
import com.example.framephone.tracking.ArPoseState

object TelemetryState {
    var status by mutableStateOf(LinkStatus())
        internal set
}

class TelemetryService : Service() {
    private var server: PhoneServer? = null
    private val main = Handler(Looper.getMainLooper())
    private val screen = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action in listOf(Intent.ACTION_SCREEN_ON, Intent.ACTION_USER_PRESENT) &&
                SettingsStore(this@TelemetryService).connectionEnabled() && !TelemetryState.status.connected) {
                BluetoothPose.retryConnection()
            }
        }
    }
    override fun onCreate() {
        super.onCreate()
        androidx.core.content.ContextCompat.registerReceiver(this, screen, IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_USER_PRESENT)
        }, androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val store = SettingsStore(this)
        when (intent?.action) {
            "companion_changed" -> {
                BluetoothPose.close()
                server?.disconnectClient()
                ArPoseState.setConnected(false)
                return START_NOT_STICKY
            }
            "stop", "forget" -> {
                store.enableConnection(false)
                BluetoothPose.close()
                if (intent.action == "forget") runCatching { CompanionSetup.forget(this) }
                ArPoseState.setConnected(false)
                stopService(Intent(this, ArPoseService::class.java))
                server?.close()
                server = null
                if (intent.action == "forget") {
                    store.forget()
                    BluetoothPose.lastFailure = ""
                }
                TelemetryState.status = LinkStatus(paired = store.pairedName())
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
        }
        if (intent?.action == "wake" && !store.connectionEnabled()) { stopSelf(); return START_NOT_STICKY }
        if (intent?.action != "wake") store.enableConnection(true)
        runCatching {
            BluetoothPose.start(this, ArPoseState::message,
                bondLost = { main.post { server?.disconnectClient() } },
                trackingChanged = { _ -> main.post {
                    if (SettingsStore(this).connectionEnabled()) {
                        val active = BluetoothPose.standalone() || TelemetryState.status.connected
                        val newlyConnected = active && !ArPoseState.connected
                        ArPoseState.setConnected(active)
                        if (newlyConnected) CompanionSetup.resumeCamera(this)
                    }
                } })
        }
        if (server != null) {
            if (!TelemetryState.status.connected) BluetoothPose.retryConnection()
            return START_NOT_STICKY
        }
        val dimensions = store.dimensions()
        if (dimensions == null) { stopSelf(); return START_NOT_STICKY }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("telemetry", "Phone telemetry", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, TelemetryService::class.java).setAction("stop"), PendingIntent.FLAG_IMMUTABLE)
        startForeground(1, Notification.Builder(this, "telemetry")
            .setSmallIcon(android.R.drawable.stat_notify_sync).setContentTitle("FramePhone")
            .setContentText("Connection enabled")
            .setContentIntent(open).setOngoing(true).addAction(Notification.Action.Builder(null, "Stop", stop).build()).build())
        TelemetryState.status = LinkStatus(running = true, message = "Starting secure listener…", paired = store.pairedName())
        lateinit var instance: PhoneServer
        instance = PhoneServer(this, store, dimensions) { status ->
            main.post {
                if (server === instance) {
                    TelemetryState.status = status
                    val active = status.connected || BluetoothPose.standalone()
                    val newlyConnected = active && !ArPoseState.connected
                    ArPoseState.setConnected(active)
                    if (newlyConnected) CompanionSetup.resumeCamera(this)
                    if (!status.running) {
                        // The LAN listener can fail independently of Bluetooth.
                        // Keep the foreground service and authenticated radio alive.
                        server = null
                        TelemetryState.status = status.copy(running = true)
                    }
                }
            }
        }
        server = instance
        instance.start()
        return START_NOT_STICKY
    }
    override fun onDestroy() {
        unregisterReceiver(screen)
        BluetoothPose.close()
        ArPoseState.setConnected(false)
        stopService(Intent(this, ArPoseService::class.java))
        server?.close()
        server = null
        if (TelemetryState.status.running) TelemetryState.status = LinkStatus(paired = SettingsStore(this).pairedName())
        super.onDestroy()
    }
}
