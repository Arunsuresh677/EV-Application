package com.evplatform.driver.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp

// Mirrors the web prototype's tokens so driver-web and driver-Android read as one product.
object EVColor {
    val bgDeep = Color(0xFF0B0F14)
    val bgPanel = Color(0xFF131A21)
    val bgRaise = Color(0xFF1B2530)
    val line = Color(0xFF232F3B)
    val lime = Color(0xFFB4F461)     // available / go
    val amber = Color(0xFFFFB454)    // charging in progress
    val red = Color(0xFFFF6B5E)      // fault
    val textMain = Color(0xFFF2F6F5)
    val textMuted = Color(0xFF7C8B93)
}

/** Register actual variable fonts (Space Grotesk / Inter / JetBrains Mono) via
 *  res/font/ and swap these for FontFamily(Font(R.font.xxx)) once added. */
object EVFont {
    val display = FontFamily.SansSerif
    val body = FontFamily.Default
    val mono = FontFamily.Monospace
}

/**
 * Concentric radius system — mirrors web/static/styles.css exactly, so
 * driver-web and driver-Android read as the same shape language. Each step
 * is the level above it minus that container's own padding, so nested
 * corners share a center point instead of looking arbitrary. `capsule` uses
 * `percent = 50`, Compose's equivalent of radius = height/2 — always a
 * perfect capsule regardless of the element's actual height.
 */
object EVRadius {
    val container = 24.dp   // outermost shells: bottom sheets, full-screen cards
    val panel = 16.dp        // one level in: cards, banners
    val element = 10.dp      // one level in from a panel: stat boxes, small inputs
    val capsule = RoundedCornerShape(percent = 50)  // buttons, pills, badges, switches, sliders
}

// FAULTED (system/Plug-Watch auto-detected) and MAINTENANCE (operator's own
// manual toggle) are technically distinct server-side but shown to drivers
// under one calm label — they don't need to know which it is, just that
// it's not available. The operator dashboard keeps the distinction.
enum class ConnectorStatus(val label: String) {
    AVAILABLE("Available"),
    OCCUPIED("Occupied"),
    FAULTED("Under maintenance"),
    RESERVED("Reserved"),
    MAINTENANCE("Under maintenance");

    val color: Color
        get() = when (this) {
            AVAILABLE -> EVColor.lime
            OCCUPIED -> EVColor.amber
            FAULTED, MAINTENANCE -> EVColor.red
            RESERVED -> EVColor.textMuted
        }
}
