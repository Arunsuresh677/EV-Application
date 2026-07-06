package com.evplatform.driver.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.evplatform.driver.model.HistoryEntry
import com.evplatform.driver.model.SessionStatus
import com.evplatform.driver.ui.theme.EVColor
import java.text.SimpleDateFormat
import java.util.*

@Composable
fun HistoryScreen(entries: List<HistoryEntry>) {
    Column(Modifier.fillMaxSize().background(EVColor.bgDeep)) {
        Column(Modifier.padding(20.dp)) {
            Text("${entries.size} SESSIONS", color = EVColor.textMuted, fontSize = 11.sp)
            Text("Charging history", color = EVColor.textMain, fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
        }

        LazyColumn {
            items(entries) { entry -> HistoryRow(entry) }
        }
    }
}

private val dateFormat = SimpleDateFormat("MMM d · h:mm a", Locale.getDefault())

private fun statusColor(status: SessionStatus): Color = when (status) {
    SessionStatus.COMPLETED -> EVColor.lime
    SessionStatus.FAILED -> EVColor.red
    SessionStatus.STOPPED_REMOTELY -> EVColor.amber
    else -> EVColor.textMuted
}

@Composable
private fun HistoryRow(entry: HistoryEntry) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Column {
            Text(dateFormat.format(Date(entry.startTime ?: entry.endTime ?: 0L)), color = EVColor.textMuted, fontSize = 11.sp)
            Text("Connector ${entry.connectorId.toString().take(8)}", color = EVColor.textMain, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            Row {
                Text(entry.status.name, color = statusColor(entry.status), fontSize = 10.sp)
                entry.claimAmount?.let {
                    Text(" · ₹%.2f credited".format(it), color = EVColor.lime, fontSize = 10.sp)
                }
            }
        }
        Column(horizontalAlignment = Alignment.End) {
            Text("₹%.2f".format(entry.cost ?: 0.0), color = EVColor.textMain, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Text("%.1f kWh".format(entry.energyKwh ?: 0.0), color = EVColor.textMuted, fontSize = 11.sp)
        }
    }
}
