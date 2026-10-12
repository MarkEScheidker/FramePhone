package com.example.framephone.markers

/** AprilTag 3 v3.4.5 tag36h11 IDs 0–5. See assets/APRILTAG_LICENSE.txt.
 * Coordinates and bit order are from tag36h11.c and apriltag_to_image, NOT row-major codes.
 */
object Tag36h11 {
    const val FAMILY = "tag36h11"
    const val SOURCE = "AprilRobotics/apriltag v3.4.5"
    private val codes = longArrayOf(0xD7E00984BL, 0xDDA664CA7L, 0xDC4A1C821L, 0xE17B470E9L,
        0xEF91D01B1L, 0xF429CDD73L)
    private val xs = intArrayOf(1,2,3,4,5,2,3,4,3,6,6,6,6,6,5,5,5,4,6,5,4,3,2,5,4,3,4,1,1,1,1,1,2,2,2,3)
    private val ys = intArrayOf(1,1,1,1,1,2,2,2,3,1,2,3,4,5,2,3,4,3,6,6,6,6,6,5,5,5,4,6,5,4,3,2,5,4,3,4)

    /** True = white. A 10x10 raster includes the complete one-cell white quiet border. */
    fun cells(id: Int): BooleanArray {
        require(id in codes.indices)
        val cells = BooleanArray(100) { i -> i % 10 == 0 || i % 10 == 9 || i / 10 == 0 || i / 10 == 9 }
        xs.indices.forEach { bit ->
            cells[(ys[bit] + 1) * 10 + xs[bit] + 1] = (codes[id] and (1L shl (35 - bit))) != 0L
        }
        return cells
    }
}
