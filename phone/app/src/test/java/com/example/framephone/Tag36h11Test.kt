package com.example.framephone

import com.example.framephone.markers.Tag36h11
import org.junit.Assert.*
import org.junit.Test

class Tag36h11Test {
    // Independent upstream PNG fixtures, retrieved 2026-10-11 from:
    // https://github.com/AprilRobotics/apriltag-imgs/tree/master/tag36h11
    // tag36_11_00000.png through tag36_11_00003.png. CRC-verified PNGs decoded to
    // white=1, black=0 rows, not produced by the Kotlin renderer or codewords.
    private val officialPixels = listOf(
        "1111111111/1000000001/1011010101/1001110101/1001100001/1010100001/1001011001/1000010001/1000000001/1111111111",
        "1111111111/1000000001/1011011001/1001011101/1011110001/1001100001/1010110101/1000100101/1000000001/1111111111",
        "1111111111/1000000001/1011011101/1001001001/1010000001/1000100101/1000010001/1000111001/1000000001/1111111111",
        "1111111111/1000000001/1011100101/1000011101/1010011101/1010100101/1011001001/1001100001/1000000001/1111111111",
    )

    @Test fun allFourMarkersMatchOfficialImagesPixelForPixel() {
        officialPixels.forEachIndexed { id, pixels ->
            val rows = pixels.split('/')
            assertEquals(10, rows.size)
            assertTrue(rows.all { it.length == 10 })
            val cells = Tag36h11.cells(id)
            for (y in 0..9) for (x in 0..9) {
                assertEquals("ID $id pixel ($x,$y)", rows[y][x] == '1', cells[y * 10 + x])
            }
        }
    }

    @Test fun whiteQuietZoneAndBlackDetectionBorderArePreserved() {
        for (id in 0..5) {
            val cells = Tag36h11.cells(id)
            for (i in 0..9) {
                assertTrue(cells[i]); assertTrue(cells[90 + i]); assertTrue(cells[i * 10]); assertTrue(cells[i * 10 + 9])
            }
            for (i in 1..8) {
                assertFalse(cells[10 + i]); assertFalse(cells[80 + i]); assertFalse(cells[i * 10 + 1]); assertFalse(cells[i * 10 + 8])
            }
        }
    }

    @Test fun unknownIdsAreRejected() {
        assertThrows(IllegalArgumentException::class.java) { Tag36h11.cells(6) }
        assertThrows(IllegalArgumentException::class.java) { Tag36h11.cells(-1) }
    }
}
