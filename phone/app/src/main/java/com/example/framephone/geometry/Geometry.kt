package com.example.framephone.geometry

import kotlin.math.roundToInt

data class PixelPoint(val x: Int, val y: Int)
data class Vec3(val x: Double, val y: Double, val z: Double = 0.0)
data class PixelRect(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val width get() = right - left
    val height get() = bottom - top
    fun contains(other: PixelRect) = other.left >= left && other.top >= top &&
        other.right <= right && other.bottom <= bottom
    fun intersects(other: PixelRect) = left < other.right && right > other.left &&
        top < other.bottom && bottom > other.top
}

enum class MarkerLayout(val label: String, val ids: Set<Int>) {
    FOUR_CORNERS("Four corners", setOf(0, 1, 2, 3)),
    TWO_DIAGONAL("Two diagonal corners", setOf(0, 2)),
    FOUR_EDGES("Four edge centers", setOf(0, 1, 2, 3)),
    SIX_PHONE_FRAME("Six: corners and side centers", (0..5).toSet()),
}
enum class OrientationPolicy { FOLLOW_DISPLAY, PORTRAIT_ONLY, LANDSCAPE_ONLY }

data class OverlayConfig(
    val layout: MarkerLayout = MarkerLayout.FOUR_CORNERS,
    val markerSizeMm: Double = 16.0,
    val marginMm: Double = 2.0,
    val orientation: OrientationPolicy = OrientationPolicy.FOLLOW_DISPLAY,
) {
    init {
        require(markerSizeMm.isFinite() && markerSizeMm in 8.0..20.0)
        require(marginMm.isFinite() && marginMm in 0.0..20.0)
    }
}

data class ScreenCalibration(
    val key: String,
    val portraitWidthM: Double,
    val portraitHeightM: Double,
    val measuredAtEpochMs: Long,
) {
    init {
        require(portraitWidthM.isFinite() && portraitWidthM in 0.02..0.5)
        require(portraitHeightM.isFinite() && portraitHeightM in portraitWidthM..0.8)
        require(key.isNotBlank() && measuredAtEpochMs > 0)
    }
}

/** Pixel coordinates use pixel edges, not pixel centers. Rotation is Android Surface.rotation. */
data class DisplayGeometry(
    val widthPx: Int,
    val heightPx: Int,
    val rotation: Int,
    val naturalPortrait: Boolean,
    val calibration: ScreenCalibration,
) {
    init { require(widthPx > 0 && heightPx > 0 && rotation in 0..3) }
    // Landscape-natural displays have canonical portrait at Surface.ROTATION_90.
    val portraitQuarterTurns get() = (rotation - (if (naturalPortrait) 0 else 1) + 4) % 4
    val landscape get() = portraitQuarterTurns % 2 == 1
    val displayWidthM get() = if (landscape) calibration.portraitHeightM else calibration.portraitWidthM
    val displayHeightM get() = if (landscape) calibration.portraitWidthM else calibration.portraitHeightM
    val metersPerPixelX get() = displayWidthM / widthPx
    val metersPerPixelY get() = displayHeightM / heightPx

    /** D is centered, x right, y up, z out. Returns coordinates in canonical portrait P. */
    fun toPhone(point: PixelPoint): Vec3 {
        val x = (point.x - widthPx / 2.0) * metersPerPixelX
        val y = (heightPx / 2.0 - point.y) * metersPerPixelY
        return when (portraitQuarterTurns) {
            0 -> Vec3(x, y)
            1 -> Vec3(y, -x)
            2 -> Vec3(-x, -y)
            else -> Vec3(-y, x)
        }
    }

    /** Maps a point in the phone's portrait frame back to this display's pixel grid. */
    fun fromPhone(point: Vec3): PixelPoint {
        val (x, y) = when (portraitQuarterTurns) {
            0 -> point.x to point.y
            1 -> -point.y to point.x
            2 -> -point.x to -point.y
            else -> point.y to -point.x
        }
        return PixelPoint((x / metersPerPixelX + widthPx / 2.0).roundToInt(),
            (heightPx / 2.0 - y / metersPerPixelY).roundToInt())
    }
}

data class RenderedMarker(
    val id: Int,
    val bounds: PixelRect,
    val cellWidthPx: Int,
    val cellHeightPx: Int,
    /** Clockwise turns applied to the generated tag raster in display coordinates. */
    val imageRotationQuarterTurns: Int = 0,
) {
    // tag36h11: outer white ring is 1 cell; detector boundary encloses the inner 8x8.
    // Order follows the rendered raster; detector adapters must reorder explicitly.
    val cornersPx: List<PixelPoint> get() = listOf(
        PixelPoint(bounds.left + cellWidthPx, bounds.top + cellHeightPx),
        PixelPoint(bounds.right - cellWidthPx, bounds.top + cellHeightPx),
        PixelPoint(bounds.right - cellWidthPx, bounds.bottom - cellHeightPx),
        PixelPoint(bounds.left + cellWidthPx, bounds.bottom - cellHeightPx),
    )
    fun cornersM(display: DisplayGeometry) = cornersPx.map(display::toPhone)
}

object MarkerGeometry {
    fun layout(display: DisplayGeometry, usable: PixelRect, config: OverlayConfig): List<RenderedMarker> {
        require(PixelRect(0, 0, display.widthPx, display.heightPx).contains(usable))
        require(usable.width > 0 && usable.height > 0)
        require(config.orientation != OrientationPolicy.PORTRAIT_ONLY || !display.landscape) {
            "Overlay paused: portrait-only configuration"
        }
        require(config.orientation != OrientationPolicy.LANDSCAPE_ONLY || display.landscape) {
            "Overlay paused: landscape-only configuration"
        }
        val canonical = DisplayGeometry(
            if (display.landscape) display.heightPx else display.widthPx,
            if (display.landscape) display.widthPx else display.heightPx,
            if (display.naturalPortrait) 0 else 1,
            display.naturalPortrait,
            display.calibration,
        )
        val canonicalUsable = toCanonicalBounds(display, usable, canonical)
        val base = layoutInFrame(canonical, canonicalUsable, config)
        val turns = display.portraitQuarterTurns
        val mapped = if (turns == 0) base else base.map { marker ->
            val corners = listOf(
                PixelPoint(marker.bounds.left, marker.bounds.top),
                PixelPoint(marker.bounds.right, marker.bounds.top),
                PixelPoint(marker.bounds.right, marker.bounds.bottom),
                PixelPoint(marker.bounds.left, marker.bounds.bottom),
            ).map { display.fromPhone(canonical.toPhone(it)) }
            val bounds = PixelRect(corners.minOf { it.x }, corners.minOf { it.y },
                corners.maxOf { it.x }, corners.maxOf { it.y })
            RenderedMarker(marker.id, bounds,
                if (turns % 2 == 0) marker.cellWidthPx else marker.cellHeightPx,
                if (turns % 2 == 0) marker.cellHeightPx else marker.cellWidthPx,
                (4 - turns) % 4)
        }
        validate(mapped, usable)
        return mapped
    }

    private fun toCanonicalBounds(display: DisplayGeometry, bounds: PixelRect, canonical: DisplayGeometry): PixelRect {
        val points = listOf(
            PixelPoint(bounds.left, bounds.top), PixelPoint(bounds.right, bounds.top),
            PixelPoint(bounds.right, bounds.bottom), PixelPoint(bounds.left, bounds.bottom),
        ).map { point ->
            val physical = display.toPhone(point)
            PixelPoint(
                (physical.x / canonical.metersPerPixelX + canonical.widthPx / 2.0).roundToInt(),
                (canonical.heightPx / 2.0 - physical.y / canonical.metersPerPixelY).roundToInt(),
            )
        }
        return PixelRect(points.minOf { it.x }, points.minOf { it.y }, points.maxOf { it.x }, points.maxOf { it.y })
    }

    private fun layoutInFrame(display: DisplayGeometry, usable: PixelRect, config: OverlayConfig): List<RenderedMarker> {
        val cw = (config.markerSizeMm / 1000 / display.metersPerPixelX / 8).roundToInt()
        val ch = (config.markerSizeMm / 1000 / display.metersPerPixelY / 8).roundToInt()
        require(cw >= 1 && ch >= 1) { "Display resolution is too low" }
        val w = 10 * cw
        val h = 10 * ch
        val mx = (config.marginMm / 1000 / display.metersPerPixelX).roundToInt()
        val my = (config.marginMm / 1000 / display.metersPerPixelY).roundToInt()
        val l = usable.left + mx
        val t = usable.top + my
        val r = usable.right - mx - w
        val b = usable.bottom - my - h
        val cx = (usable.left + usable.right - w) / 2
        val cy = (usable.top + usable.bottom - h) / 2
        val corners = listOf(
            0 to PixelPoint(l, t), 1 to PixelPoint(r, t),
            2 to PixelPoint(r, b), 3 to PixelPoint(l, b),
        )
        val positions = when (config.layout) {
            MarkerLayout.FOUR_CORNERS -> corners
            MarkerLayout.TWO_DIAGONAL -> corners.filter { it.first in config.layout.ids }
            MarkerLayout.FOUR_EDGES -> listOf(0 to PixelPoint(cx, t), 1 to PixelPoint(r, cy),
                2 to PixelPoint(cx, b), 3 to PixelPoint(l, cy))
            MarkerLayout.SIX_PHONE_FRAME -> corners + listOf(4 to PixelPoint(r, cy), 5 to PixelPoint(l, cy))
        }
        val markers = positions.map { (id, p) -> RenderedMarker(id, PixelRect(p.x, p.y, p.x + w, p.y + h), cw, ch) }
        validate(markers, usable)
        return markers
    }

    fun validate(markers: List<RenderedMarker>, usable: PixelRect) {
        val ids = markers.map { it.id }.toSet()
        require(markers.size == ids.size && MarkerLayout.entries.any { it.ids == ids }) {
            "Marker IDs must match a supported layout without duplicates"
        }
        markers.forEach { marker ->
            require(marker.id in 0..5 && marker.cellWidthPx > 0 && marker.cellHeightPx > 0) {
                "Marker ${marker.id} has invalid cell dimensions"
            }
            require(marker.bounds.width == marker.cellWidthPx * 10 && marker.bounds.height == marker.cellHeightPx * 10) {
                "Marker ${marker.id} window does not match its 10×10 raster"
            }
            require(usable.contains(marker.bounds)) {
                "Marker ${marker.id} (${marker.bounds.width}×${marker.bounds.height} px, including quiet zone) " +
                    "does not fit usable bounds ${usable.width}×${usable.height} px; reduce size or margin"
            }
        }
        markers.forEachIndexed { i, a -> markers.drop(i + 1).forEach { b ->
            if (a.bounds.intersects(b.bounds)) {
                val overlapX = minOf(a.bounds.right, b.bounds.right) - maxOf(a.bounds.left, b.bounds.left)
                val overlapY = minOf(a.bounds.bottom, b.bounds.bottom) - maxOf(a.bounds.top, b.bounds.top)
                throw IllegalArgumentException("Markers ${a.id} and ${b.id} overlap by ${overlapX}×${overlapY} px; reduce size or margin")
            }
        } }
    }
}
