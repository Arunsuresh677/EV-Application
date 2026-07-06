package com.evplatform.driver.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily

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
