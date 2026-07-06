package com.evplatform.driver.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.evplatform.driver.model.Connector
import com.evplatform.driver.model.PlugWatchIssueType
import com.evplatform.driver.network.ApiClient
import com.evplatform.driver.ui.theme.EVColor
import com.evplatform.driver.ui.theme.EVRadius
import kotlinx.coroutines.launch

/**
 * Crowdsourced fault reporting. Two reports on a connector the network
 * still shows as fine auto-flags it and opens a maintenance ticket
 * server-side (see ApiClient.reportIssue) — this is the client half of
 * that loop.
 */
@Composable
fun PlugWatchReportSheet(connector: Connector, apiClient: ApiClient, onDismiss: () -> Unit) {
    var issueType by remember { mutableStateOf(PlugWatchIssueType.WONT_CHARGE) }
    var note by remember { mutableStateOf("") }
    var isSubmitting by remember { mutableStateOf(false) }
    var resultMessage by remember { mutableStateOf<String?>(null) }
    var menuExpanded by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(topStart = EVRadius.container, topEnd = EVRadius.container))
            .background(EVColor.bgPanel)
            .padding(20.dp)
    ) {
        Text("Report an issue", color = EVColor.textMain, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        Text(
            "Two reports on a connector the network still shows as fine will auto-flag it — Plug Watch catches faults the hardware feed misses.",
            color = EVColor.textMuted, fontSize = 13.sp
        )
        Spacer(Modifier.height(14.dp))

        Text("ISSUE TYPE", color = EVColor.textMuted, fontSize = 11.sp)
        Box {
            Row(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(EVRadius.element))
                    .background(EVColor.bgRaise)
                    .padding(12.dp)
                    .let { it }
            ) {
                Text(issueType.label, color = EVColor.textMain, fontSize = 14.sp)
            }
            DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                PlugWatchIssueType.values().forEach { type ->
                    DropdownMenuItem(text = { Text(type.label) }, onClick = { issueType = type; menuExpanded = false })
                }
            }
        }
        Spacer(Modifier.height(4.dp))
        TextButton(onClick = { menuExpanded = true }) { Text("Change issue type", color = EVColor.lime, fontSize = 12.sp) }

        Spacer(Modifier.height(10.dp))
        Text("DETAILS (OPTIONAL)", color = EVColor.textMuted, fontSize = 11.sp)
        OutlinedTextField(
            value = note,
            onValueChange = { note = it },
            placeholder = { Text("What happened?") },
            keyboardOptions = KeyboardOptions.Default,
            modifier = Modifier.fillMaxWidth().height(80.dp)
        )

        resultMessage?.let {
            Spacer(Modifier.height(10.dp))
            Text(it, color = EVColor.lime, fontSize = 13.sp)
        }

        Spacer(Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(
                onClick = onDismiss,
                colors = ButtonDefaults.buttonColors(containerColor = EVColor.bgRaise, contentColor = EVColor.textMain),
                shape = EVRadius.capsule,
                modifier = Modifier.weight(1f)
            ) { Text("Cancel") }

            Button(
                shape = EVRadius.capsule,
                onClick = {
                    isSubmitting = true
                    scope.launch {
                        try {
                            val result = apiClient.reportIssue(connector.id, issueType, note.ifBlank { null })
                            resultMessage = if (result.ticketOpened) {
                                "Reported. Enough Plug Watch reports came in — connector flagged and a maintenance ticket opened."
                            } else {
                                "Thanks — report recorded."
                            }
                        } catch (e: Exception) {
                            resultMessage = "Could not submit report. Try again."
                        } finally {
                            isSubmitting = false
                        }
                    }
                },
                enabled = !isSubmitting,
                colors = ButtonDefaults.buttonColors(containerColor = EVColor.lime, contentColor = EVColor.bgDeep),
                modifier = Modifier.weight(1f)
            ) { Text(if (isSubmitting) "Submitting…" else "Submit report") }
        }
    }
}
