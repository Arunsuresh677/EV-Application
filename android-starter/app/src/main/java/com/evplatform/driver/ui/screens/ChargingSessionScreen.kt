package com.evplatform.driver.ui.screens

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.evplatform.driver.model.ChargingSession
import com.evplatform.driver.model.InsuranceClaim
import com.evplatform.driver.model.SessionStatus
import com.evplatform.driver.network.ApiClient
import com.evplatform.driver.ui.theme.EVColor

/**
 * Live session screen. `session` is expected to update via SessionSocket
 * (WebSocket, fed by OCPP MeterValues) — not by polling — see ApiClient.kt.
 */
@Composable
fun ChargingSessionScreen(
    session: ChargingSession?,
    batteryCapacityKwh: Double,
    apiClient: ApiClient,
    onStop: () -> Unit
) {
    val percent = if (session != null && batteryCapacityKwh > 0)
        (session.energyKwh / batteryCapacityKwh).coerceIn(0.0, 1.0) else 0.0
    val isDone = session?.status in setOf(SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.STOPPED_REMOTELY)

    var claim by remember { mutableStateOf<InsuranceClaim?>(null) }

    // The instant a Guaranteed connector's session fails, insurance.py has already
    // auto-filed the claim server-side — this just fetches it to show the driver.
    LaunchedEffect(session?.status, session?.id) {
        if (session?.status == SessionStatus.FAILED) {
            claim = apiClient.claim(session.id)
        }
    }

    Column(
        Modifier.fillMaxSize().background(EVColor.bgDeep).padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Column(Modifier.fillMaxWidth()) {
            Text("LIVE SESSION", color = EVColor.textMuted, fontSize = 11.sp)
            Text("Charging", color = EVColor.textMain, fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
        }

        Spacer(Modifier.height(24.dp))
        ChargeRing(percent = percent.toFloat(), status = session?.status ?: SessionStatus.PENDING)
        Spacer(Modifier.height(24.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
            MiniStat("%.1f".format(session?.energyKwh ?: 0.0), "kWh delivered")
            MiniStat("₹${(session?.cost ?: 0.0).toInt()}", "cost so far")
            MiniStat("${(session?.powerKw ?: 0.0).toInt()} kW", "charge rate")
        }

        if (session?.status == SessionStatus.FAILED) {
            Spacer(Modifier.height(16.dp))
            FailBanner(claim)
        }

        if (!isDone) {
            Spacer(Modifier.height(20.dp))
            OutlinedButton(
                onClick = onStop,
                modifier = Modifier.fillMaxWidth().height(52.dp),
                shape = RoundedCornerShape(14.dp)
            ) { Text("Stop charging", color = EVColor.textMain) }
        }
    }
}

/**
 * Surfaces the guaranteed-charge insurance outcome — auto-filed server-side
 * the instant a Guaranteed connector's session fails (see
 * backend/app/services/insurance.py). No "file a claim" step for the driver.
 */
@Composable
private fun FailBanner(claim: InsuranceClaim?) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(EVColor.red.copy(alpha = 0.12f))
            .border(1.dp, EVColor.red, RoundedCornerShape(14.dp))
            .padding(14.dp)
    ) {
        Text("⚠ Station fault", color = EVColor.red, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        Spacer(Modifier.height(4.dp))
        if (claim != null) {
            Text(
                "✓ ₹%.2f guaranteed-charge credit issued automatically".format(claim.creditAmount),
                color = EVColor.lime, fontSize = 13.sp
            )
        } else {
            Text("The connector faulted mid-session.", color = EVColor.textMuted, fontSize = 13.sp)
        }
    }
}

/** The signature element — a segmented gauge, not a generic progress bar. */
@Composable
private fun ChargeRing(percent: Float, status: SessionStatus) {
    val animated by animateFloatAsState(targetValue = percent, label = "chargeRing")
    val ringColor = when (status) {
        SessionStatus.FAILED -> EVColor.red
        SessionStatus.COMPLETED, SessionStatus.STOPPED_REMOTELY -> EVColor.lime
        else -> EVColor.amber
    }
    Box(Modifier.size(230.dp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(230.dp)) {
            val stroke = Stroke(width = 14.dp.toPx(), cap = StrokeCap.Round)
            drawArc(EVColor.bgRaise, 0f, 360f, false, style = stroke, size = Size(size.width, size.height))
            drawArc(ringColor, -90f, 360f * animated.coerceAtLeast(0.02f), false, style = stroke, size = Size(size.width, size.height))
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("${(animated * 100).toInt()}%", color = EVColor.textMain, fontSize = 44.sp, fontWeight = FontWeight.Bold)
            Text("● ${status.name}", color = ringColor, fontSize = 11.sp)
        }
    }
}

@Composable
private fun RowScope.MiniStat(value: String, label: String) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier.weight(1f).clip(RoundedCornerShape(14.dp)).background(EVColor.bgPanel).padding(vertical = 12.dp)
    ) {
        Text(value, color = EVColor.textMain, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        Text(label.uppercase(), color = EVColor.textMuted, fontSize = 9.sp)
    }
}
