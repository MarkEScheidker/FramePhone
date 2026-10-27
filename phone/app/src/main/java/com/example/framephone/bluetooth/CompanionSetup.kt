package com.example.framephone.bluetooth

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.bluetooth.le.ScanFilter
import android.companion.AssociationInfo
import android.companion.AssociationRequest
import android.companion.BluetoothLeDeviceFilter
import android.companion.CompanionDeviceManager
import android.companion.CompanionDeviceService
import android.companion.DevicePresenceEvent
import android.companion.ObservingDevicePresenceRequest
import android.content.Context
import android.content.Intent
import android.content.IntentSender
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import com.example.framephone.SettingsStore
import com.example.framephone.link.TelemetryService
import com.example.framephone.tracking.ArPoseService
import com.example.framephone.tracking.ArPoseState

/** Android owns device selection/presence. Association is separate from GATT and app trust. */
object CompanionSetup {
    @Suppress("DEPRECATION")
    fun associate(context: Context, pending: (IntentSender) -> Unit, created: (AssociationInfo) -> Unit,
                  failed: (String) -> Unit) {
        require(context.packageManager.hasSystemFeature(PackageManager.FEATURE_COMPANION_DEVICE_SETUP)) {
            "Companion device setup is unavailable on this phone"
        }
        val filter = BluetoothLeDeviceFilter.Builder().setScanFilter(ScanFilter.Builder()
            .setServiceUuid(ParcelUuid(BleProtocol.SERVICE)).build()).build()
        val request = AssociationRequest.Builder().addDeviceFilter(filter).setSingleDevice(false).build()
        context.getSystemService(CompanionDeviceManager::class.java).associate(request,
            object : CompanionDeviceManager.Callback() {
                override fun onDeviceFound(chooserLauncher: IntentSender) = pending(chooserLauncher)
                override fun onAssociationPending(intentSender: IntentSender) = pending(intentSender)
                override fun onAssociationCreated(info: AssociationInfo) = created(info)
                override fun onFailure(error: CharSequence?) = failed(error?.toString() ?: "Bluetooth selection cancelled")
            }, Handler(Looper.getMainLooper()))
    }

    @Suppress("DEPRECATION")
    fun remember(context: Context, address: String, id: Int = -1) {
        check(context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED) {
            "Bluetooth access is required"
        }
        val store = SettingsStore(context)
        store.companion(address, id)
        // The BLE client owns bonding on its LE connection and waits for the
        // result before negotiating GATT. Association alone is not a bond.
        observe(context)
    }

    @Suppress("DEPRECATION")
    fun associated(context: Context): Boolean {
        val address = SettingsStore(context).bluetoothAddress() ?: return false
        val manager = context.getSystemService(CompanionDeviceManager::class.java)
        return if (Build.VERSION.SDK_INT >= 33)
            manager.myAssociations.any { it.deviceMacAddress?.toString().equals(address, true) }
        else manager.associations.any { it.equals(address, true) }
    }

    @Suppress("DEPRECATION")
    fun observe(context: Context) {
        val store = SettingsStore(context)
        val address = store.bluetoothAddress() ?: return
        val manager = context.getSystemService(CompanionDeviceManager::class.java)
        if (Build.VERSION.SDK_INT >= 36) {
            val association = manager.myAssociations.firstOrNull { it.deviceMacAddress?.toString().equals(address, true) }
                ?: return
            store.companion(address, association.id)
            manager.startObservingDevicePresence(ObservingDevicePresenceRequest.Builder()
                .setAssociationId(association.id).build())
        } else manager.startObservingDevicePresence(address)
    }

    @Suppress("DEPRECATION")
    fun forget(context: Context) {
        val store = SettingsStore(context)
        val address = store.bluetoothAddress() ?: return
        val manager = context.getSystemService(CompanionDeviceManager::class.java)
        if (Build.VERSION.SDK_INT >= 33) {
            manager.myAssociations.filter { it.deviceMacAddress?.toString().equals(address, true) }
                .forEach { manager.disassociate(it.id) }
        } else manager.disassociate(address)
    }

    fun resumeCamera(context: Context) {
        if (ArPoseState.running) return
        runCatching {
            context.startForegroundService(Intent(context, ArPoseService::class.java).setAction("realign"))
        }.onFailure { trackingAction(context) }
    }

    fun trackingAction(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("companion", "Companion connection", NotificationManager.IMPORTANCE_DEFAULT))
        val resume = PendingIntent.getForegroundService(context, 20,
            Intent(context, ArPoseService::class.java).setAction("realign"), PendingIntent.FLAG_IMMUTABLE)
        manager.notify(20, Notification.Builder(context, "companion")
            .setSmallIcon(android.R.drawable.ic_menu_compass).setContentTitle("FramePhone connected")
            .setContentText("Tap Resume tracking to allow camera access.")
            .setContentIntent(resume).addAction(Notification.Action.Builder(null, "Resume tracking", resume).build())
            .setAutoCancel(true).build())
    }
}

@Suppress("OVERRIDE_DEPRECATION")
class FrameCompanionService : CompanionDeviceService() {
    private fun appeared(address: String?) {
        val store = SettingsStore(this)
        if (!store.connectionEnabled() || !store.bluetoothAddress().equals(address, true)) return
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return
        // Companion presence may wake networking. A camera start still has its
        // own while-in-use restriction; notification actions provide that route.
        runCatching { startForegroundService(Intent(this, TelemetryService::class.java).setAction("wake")) }
    }
    @Suppress("DEPRECATION")
    override fun onDeviceAppeared(address: String) = appeared(address)
    override fun onDeviceAppeared(associationInfo: AssociationInfo) = appeared(associationInfo.deviceMacAddress?.toString())
    override fun onDevicePresenceEvent(event: DevicePresenceEvent) {
        if (Build.VERSION.SDK_INT >= 36 && event.event in listOf(DevicePresenceEvent.EVENT_BLE_APPEARED,
                DevicePresenceEvent.EVENT_BT_CONNECTED)) {
            val manager = getSystemService(CompanionDeviceManager::class.java)
            appeared(manager.myAssociations.firstOrNull { it.id == event.associationId }?.deviceMacAddress?.toString())
        }
    }
}
