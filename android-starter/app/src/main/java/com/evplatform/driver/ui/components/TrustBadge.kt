package com.evplatform.driver.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.evplatform.driver.ui.theme.EVColor

/**
 * The Trust Engine+ wedge, surfaced everywhere a connector appears: map
 * pins, station detail, session start confirmation. Three tiers mirror the
 * web app's badge logic exactly (see web/static/app.js `trustBadgeHtml`) —
 * Guaranteed (score >= 90, no open Plug Watch report), Good, or Low trust.
 */
@Composable
fun TrustBadge(reliabilityScore: Double, guaranteed: Boolean) {
    val (label, color) = when {
        guaranteed -> "Guaranteed" to EVColor.lime
        reliabilityScore >= 75 -> "Good" to EVColor.amber
        else -> "Low trust" to EVColor.red
    }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .clip(CircleShape)
            .background(color.copy(alpha = 0.14f))
            .border(1.dp, color.copy(alpha = 0.6f), CircleShape)
            .padding(horizontal = 10.dp, vertical = 5.dp)
    ) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(6.dp))
        Text("$label · ${reliabilityScore.toInt()}", color = color, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
    }
}
