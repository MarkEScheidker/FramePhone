package com.example.framephone.link

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.example.framephone.MainActivity
import com.example.framephone.SettingsStore

object TelemetryState {
    var status by mutableStateOf(LinkStatus())
        internal set
}

class TelemetryService : Service() {
    private var server: PhoneServer? = null
    private val main = Handler(Looper.getMainLooper())
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val store = SettingsStore(this)
        when (intent?.action) {
            "stop", "forget" -> {
                server?.close()
                server = null
                if (intent.action == "forget") store.forget()
                TelemetryState.status = LinkStatus(paired = store.pairedName())
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            "approve", "reject" -> {
                intent.getStringExtra("request")?.let { server?.approve(it, intent.action == "approve") }
                return START_NOT_STICKY
            }
        }
        if (server != null) {
            if (intent?.action == "pair") server?.openPairing()
            return START_NOT_STICKY
        }
        val dimensions = store.dimensions()
        if (dimensions == null) { stopSelf(); return START_NOT_STICKY }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("telemetry", "Phone telemetry", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, TelemetryService::class.java).setAction("stop"), PendingIntent.FLAG_IMMUTABLE)
        startForeground(1, Notification.Builder(this, "telemetry")
            .setSmallIcon(android.R.drawable.stat_notify_sync).setContentTitle("FramePhone connection enabled")
            .setContentText("Open to pair or inspect the connection. Stop to disable LAN access.")
            .setContentIntent(open).setOngoing(true).addAction(Notification.Action.Builder(null, "Stop", stop).build()).build())
        TelemetryState.status = LinkStatus(running = true, message = "Starting secure listener…", paired = store.pairedName())
        lateinit var instance: PhoneServer
        instance = PhoneServer(this, store, dimensions) { status ->
            main.post {
                if (server === instance) {
                    TelemetryState.status = status
                    if (!status.running) {
                        server = null
                        stopForeground(STOP_FOREGROUND_REMOVE)
                        stopSelf()
                    }
                }
            }
        }
        server = instance
        instance.start(intent?.action == "pair" || store.pairedName() == null)
        return START_NOT_STICKY
    }
    override fun onDestroy() {
        server?.close()
        server = null
        if (TelemetryState.status.running) TelemetryState.status = LinkStatus(paired = SettingsStore(this).pairedName())
        super.onDestroy()
    }
}
