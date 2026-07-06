package com.evplatform.driver.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.evplatform.driver.model.Connector
import com.evplatform.driver.model.Station
import com.evplatform.driver.network.ApiClient
import com.evplatform.driver.ui.components.PlugWatchReportSheet
import com.evplatform.driver.ui.components.TrustBadge
import com.evplatform.driver.ui.theme.EVColor
import com.evplatform.driver.ui.theme.EVRadius
import com.evplatform.driver.ui.theme.ConnectorStatus

/**
 * Map is left to your maps SDK of choice (Google Maps Compose / Mapbox).
 * This screen wires the station list + bottom sheet + start-charging CTA,
 * which is the part specific to this product.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MapSearchScreen(
    stations: List<Station>,
    apiClient: ApiClient,
    onStartCharging: (Station, Connector) -> Unit
) {
    var selected by remember { mutableStateOf<Station?>(stations.firstOrNull()) }
    var reportingConnector by remember { mutableStateOf<Connector?>(null) }

    Box(Modifier.fillMaxSize().background(EVColor.bgDeep)) {
        // TODO: GoogleMap(...) { stations.forEach { StationMarker(it) } }

        AnimatedVisibility(
            visible = selected != null,
            modifier = Modifier.align(Alignment.BottomCenter)
        ) {
            selected?.let { station ->
                StationDetailSheet(
                    station = station,
                    onStart = { connector -> onStartCharging(station, connector) },
                    onReportIssue = { connector -> reportingConnector = connector }
                )
            }
        }
    }

    reportingConnector?.let { connector ->
        ModalBottomSheet(onDismissRequest = { reportingConnector = null }) {
            PlugWatchReportSheet(connector = connector, apiClient = apiClient, onDismiss = { reportingConnector = null })
        }
    }
}

@Composable
private fun StationDetailSheet(station: Station, onStart: (Connector) -> Unit, onReportIssue: (Connector) -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(topStart = EVRadius.container, topEnd = EVRadius.container))
            .background(EVColor.bgPanel)
            .padding(18.dp)
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column {
                Text(station.address.uppercase(), color = EVColor.textMuted, fontSize = 11.sp)
                Text(station.name, color = EVColor.textMain, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
            }
            ReliabilityPill(station.reliabilityScore)
        }

        Spacer(Modifier.height(12.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatBox("₹${station.pricePerKwh.toInt()}", "per kWh")
            StatBox("${station.connectors.maxOf { it.powerKw }.toInt()}kW", "max speed")
            StatBox(
                "${station.connectors.count { it.status == ConnectorStatus.AVAILABLE }}/${station.connectors.size}",
                "free now"
            )
        }

        Spacer(Modifier.height(14.dp))

        station.connectors.forEach { connector -> ConnectorRow(connector, onReportIssue = { onReportIssue(connector) }) }

        Spacer(Modifier.height(14.dp))

        Button(
            onClick = { station.connectors.firstOrNull { it.status == ConnectorStatus.AVAILABLE }?.let(onStart) },
            colors = ButtonDefaults.buttonColors(containerColor = EVColor.lime, contentColor = EVColor.bgDeep),
            shape = EVRadius.capsule,
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) { Text("Start charging", fontWeight = FontWeight.SemiBold) }
    }
}

@Composable
private fun ReliabilityPill(score: Double) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.clip(EVRadius.capsule).background(EVColor.bgRaise).padding(horizontal = 10.dp, vertical = 5.dp)
    ) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(EVColor.lime))
        Spacer(Modifier.width(6.dp))
        Text("${score.toInt()}% reliable", color = EVColor.textMuted, fontSize = 11.sp)
    }
}

@Composable
private fun RowScope.StatBox(value: String, label: String) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier.weight(1f).clip(RoundedCornerShape(EVRadius.element)).background(EVColor.bgRaise).padding(10.dp)
    ) {
        Text(value, color = EVColor.textMain, fontWeight = FontWeight.Bold, fontSize = 16.sp)
        Text(label.uppercase(), color = EVColor.textMuted, fontSize = 9.sp)
    }
}

@Composable
private fun ConnectorRow(connector: Connector, onReportIssue: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 10.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text("${connector.type} · #${connector.ocppConnectorId}", color = EVColor.textMain, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                Text("${connector.powerKw.toInt()} kW", color = EVColor.textMuted, fontSize = 11.sp)
            }
            Column(horizontalAlignment = Alignment.End) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(6.dp).clip(CircleShape).background(connector.status.color))
                    Spacer(Modifier.width(6.dp))
                    Text(connector.status.label, color = EVColor.textMuted, fontSize = 11.sp)
                }
                connector.reliabilityScore?.let { score ->
                    Spacer(Modifier.height(6.dp))
                    TrustBadge(reliabilityScore = score, guaranteed = connector.guaranteed)
                }
            }
        }
        TextButton(onClick = onReportIssue, contentPadding = PaddingValues(0.dp)) {
            Text("🚩 Report an issue", color = EVColor.textMuted, fontSize = 11.sp)
        }
    }
}
