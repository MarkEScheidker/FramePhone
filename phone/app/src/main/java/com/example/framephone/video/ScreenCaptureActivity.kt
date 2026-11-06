package com.example.framephone.video

import android.app.Activity
import android.content.Intent
import android.hardware.display.DisplayManager
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.view.Display
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts

/** The system owns capture consent. Result data is used once and never saved. */
class ScreenCaptureActivity : ComponentActivity() {
    private val approval = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val bounds = getSystemService(WindowManager::class.java).maximumWindowMetrics.bounds
            try {
                startForegroundService(Intent(this, ScreenCaptureService::class.java)
                    .putExtra("consent", result.data).putExtra("width", bounds.width()).putExtra("height", bounds.height())
                    .putExtra("density", resources.configuration.densityDpi)
                    .putExtra("rotation", getSystemService(DisplayManager::class.java).getDisplay(Display.DEFAULT_DISPLAY).rotation))
            } catch (error: RuntimeException) { ScreenVideo.status = "Screen capture could not start: ${error.javaClass.simpleName}" }
        } else ScreenVideo.status = "Screen sharing not approved — tap Share screen to retry"
        finish()
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (ScreenVideo.capturing || !ScreenVideo.eligible()) { finish(); return }
        ScreenVideo.prompt.shown()
        if (savedInstanceState == null) {
            val manager = getSystemService(MediaProjectionManager::class.java)
            val request = if (Build.VERSION.SDK_INT >= 34)
                manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
                else manager.createScreenCaptureIntent()
            approval.launch(request)
        }
    }
    override fun onDestroy() {
        if (isFinishing) ScreenVideo.prompt.finished()
        super.onDestroy()
    }
}
