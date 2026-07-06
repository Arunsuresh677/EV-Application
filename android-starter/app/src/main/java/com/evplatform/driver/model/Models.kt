package com.evplatform.driver.model

import com.evplatform.driver.ui.theme.ConnectorStatus
import java.util.UUID

data class Station(
    val id: UUID,
    val name: String,
    val address: String,
    val lat: Double,
    val lng: Double,
    val reliabilityScore: Double,        // 0-100 — the platform's trust wedge
    val connectors: List<Connector>,
    val pricePerKwh: Double
)

data class Connector(
    val id: UUID,
    val ocppConnectorId: Int,
    val type: String,                    // CCS2 / CHAdeMO / TYPE2 / NACS
    val powerKw: Double,
    val status: ConnectorStatus,
    val reliabilityScore: Double?,
    val guaranteed: Boolean               // Trust Engine+ — snapshotted onto a session at start time
)

data class ChargingSession(
    val id: UUID,
    val connectorId: UUID,
    val status: SessionStatus,
    val startTime: Long,
    val endTime: Long?,
    val energyKwh: Double,
    val cost: Double,
    val powerKw: Double                  // instantaneous rate, for the live gauge
)

enum class SessionStatus { PENDING, ACTIVE, COMPLETED, FAILED, STOPPED_REMOTELY }

data class HistoryEntry(
    val id: UUID,
    val connectorId: UUID,
    val status: SessionStatus,
    val startTime: Long?,
    val endTime: Long?,
    val energyKwh: Double?,
    val cost: Double?,
    val claimAmount: Double?              // set when a Guaranteed connector failed and insurance auto-paid out
)

// ---------------------------------------------------------------------------
// Trust Engine+ — live reliability scoring, crowdsourced Plug Watch fault
// reports, and automatic guaranteed-charge insurance payouts. See
// docs/trust-engine-addendum.md.
// ---------------------------------------------------------------------------

data class ReliabilityDetail(
    val connectorId: UUID,
    val reliabilityScore: Double,
    val guaranteed: Boolean,
    val status: ConnectorStatus,
    val openPlugwatchReports: List<PlugWatchReport>
)

data class PlugWatchReport(
    val id: UUID,
    val issueType: PlugWatchIssueType,
    val note: String?,
    val createdAt: Long
)

enum class PlugWatchIssueType(val apiValue: String, val label: String) {
    WONT_CHARGE("wont_charge", "Won't charge"),
    DAMAGED("damaged", "Damaged / unsafe"),
    BLOCKED("blocked", "Blocked by another vehicle"),
    WRONG_STATUS("wrong_status", "Shows wrong status in app"),
    OTHER("other", "Other")
}

/** Result of submitting a report — tells the UI whether this report was the
 *  one that tipped the connector into an auto-opened maintenance ticket. */
data class PlugWatchReportResult(
    val reportId: UUID,
    val unresolvedReports: Int,
    val ticketOpened: Boolean,
    val reliabilityScore: Double
)

data class InsuranceClaim(
    val id: UUID,
    val sessionId: UUID,
    val connectorId: UUID,
    val reason: String,
    val creditAmount: Double,
    val createdAt: Long
)

data class WalletEntry(
    val id: UUID,
    val amount: Double,
    val reason: String,
    val createdAt: Long
)

data class Wallet(
    val balance: Double,
    val entries: List<WalletEntry>
)
