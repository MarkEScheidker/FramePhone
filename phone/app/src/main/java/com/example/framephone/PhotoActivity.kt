package com.example.framephone

import android.app.Activity
import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.WindowManager
import android.widget.ImageView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/** Fixed portrait FIT_CENTER keeps reference coordinates rigid to the phone body. */
class PhotoActivity : Activity() {
    private var photoId: String? = null
    private var bitmap: android.graphics.Bitmap? = null
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val photo = PhotoReference.current ?: run { finish(); return }
        photoId = photo.id
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.attributes = window.attributes.apply { screenBrightness = 1f }
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        bitmap = BitmapFactory.decodeByteArray(photo.png, 0, photo.png.size)
        setContentView(ImageView(this).apply {
            setBackgroundColor(android.graphics.Color.BLACK)
            scaleType = ImageView.ScaleType.FIT_CENTER
            setImageBitmap(bitmap)
            contentDescription = "Tracking photo. Tap to return."
            setOnClickListener { finish() }
        })
    }
    override fun onResume() { super.onResume(); PhotoReference.displayedId = photoId }
    override fun onPause() { PhotoReference.displayedId = null; super.onPause() }
    override fun onDestroy() { bitmap?.recycle(); bitmap = null; super.onDestroy() }
}
