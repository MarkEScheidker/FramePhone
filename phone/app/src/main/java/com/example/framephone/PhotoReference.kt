package com.example.framephone

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ColorSpace
import android.graphics.ImageDecoder
import android.graphics.Canvas
import android.graphics.Color
import android.net.Uri
import com.example.framephone.link.Protocol
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

data class PhotoAsset(val png: ByteArray, val id: String, val width: Int, val height: Int)

/** A single user-selected, bounded reference. Never captures another app's display. */
object PhotoReference {
    @Volatile var current: PhotoAsset? = null
        private set
    @Volatile var displayedId: String? = null
    fun select(context: Context, uri: Uri): PhotoAsset {
        val bytes = context.contentResolver.openInputStream(uri)?.use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                require(output.size() + count <= 16 * 1024 * 1024) { "Choose a photo smaller than 16 MiB" }
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        } ?: error("Cannot read this photo")
        val bitmap = ImageDecoder.decodeBitmap(ImageDecoder.createSource(ByteBuffer.wrap(bytes))) { decoder, info, _ ->
            val w = info.size.width; val h = info.size.height
            require(w >= 64 && h >= 64 && h.toDouble() / w in .2..5.0) { "Choose a normal landscape or portrait photo" }
            val scale = minOf(1.0, 960.0 / maxOf(w, h))
            decoder.setTargetSize(maxOf(64, (w * scale).toInt()), maxOf(64, (h * scale).toInt()))
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            decoder.setTargetColorSpace(ColorSpace.get(ColorSpace.Named.SRGB))
        }
        try {
            val opaque = Bitmap.createBitmap(bitmap.width, bitmap.height, Bitmap.Config.ARGB_8888)
            Canvas(opaque).apply { drawColor(Color.BLACK); drawBitmap(bitmap, 0f, 0f, null) }
            val output = ByteArrayOutputStream()
            try { check(opaque.compress(Bitmap.CompressFormat.PNG, 100, output)) }
            finally { opaque.recycle() }
            val png = output.toByteArray()
            require(png.size <= 2 * 1024 * 1024) { "Photo exceeds transfer limit" }
            return PhotoAsset(png, Protocol.hash(png), bitmap.width, bitmap.height).also { current = it }
        } finally { bitmap.recycle() }
    }
}
