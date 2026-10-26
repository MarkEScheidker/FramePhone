package com.example.framephone.tracking

/** Camera2 REALTIME timestamps share the IMU/elapsedRealtime epoch. Unknown clocks stay explicit. */
object PoseTiming {
    fun captureCenter(realtime: Boolean, startNs: Long?, exposureNs: Long?, skewNs: Long?, updatedAtNs: Long): Long? {
        if (!realtime || startNs == null || exposureNs == null || skewNs == null ||
            startNs <= 0 || exposureNs !in 0..100_000_000L || skewNs !in 0..100_000_000L) return null
        val center = startNs + exposureNs/2 + skewNs/2
        return center.takeIf { it > 0 && updatedAtNs-it in 0..200_000_000L }
    }
}
