import Foundation

struct Station: Identifiable, Codable {
    let id: UUID
    let name: String
    let address: String
    let lat: Double
    let lng: Double
    let reliabilityScore: Double        // 0-100 — the platform's trust wedge
    let connectors: [Connector]
    let pricePerKwh: Double
}

struct Connector: Identifiable, Codable {
    let id: UUID
    let ocppConnectorId: Int
    let type: String                    // CCS2 / CHAdeMO / TYPE2 / NACS
    let powerKw: Double
    var status: ConnectorStatus
    let reliabilityScore: Double?
    let guaranteed: Bool                // Trust Engine+ — snapshotted onto a session at start time
}

struct ChargingSession: Identifiable, Codable {
    let id: UUID
    let connectorId: UUID
    var status: SessionStatus
    let startTime: Date
    var endTime: Date?
    var energyKwh: Double
    var cost: Double
    var powerKw: Double                 // current instantaneous rate, for the live gauge
}

enum SessionStatus: String, Codable {
    case pending, active, completed, failed
    // convertFromSnakeCase applies to struct keys, not enum raw values, so
    // this needs an explicit raw value to match the backend's "stopped_remotely".
    case stoppedRemotely = "stopped_remotely"
}

struct HistoryEntry: Identifiable, Codable {
    let id: UUID
    let connectorId: UUID
    let status: SessionStatus
    let startTime: Date?
    let endTime: Date?
    let energyKwh: Double?
    let cost: Double?
    let claimAmount: Double?   // set when a Guaranteed connector failed and insurance auto-paid out
}

// MARK: - Trust Engine+
// Live reliability scoring, crowdsourced Plug Watch fault reports, and
// automatic guaranteed-charge insurance payouts — see docs/trust-engine-addendum.md.

struct ReliabilityDetail: Codable {
    let connectorId: UUID
    let reliabilityScore: Double
    let guaranteed: Bool
    let status: ConnectorStatus
    let openPlugwatchReports: [PlugWatchReport]
}

struct PlugWatchReport: Identifiable, Codable {
    let id: UUID
    let issueType: PlugWatchIssueType
    let note: String?
    let createdAt: Date
}

enum PlugWatchIssueType: String, Codable, CaseIterable {
    case wontCharge = "wont_charge"
    case damaged
    case blocked
    case wrongStatus = "wrong_status"
    case other

    var label: String {
        switch self {
        case .wontCharge: return "Won't charge"
        case .damaged: return "Damaged / unsafe"
        case .blocked: return "Blocked by another vehicle"
        case .wrongStatus: return "Shows wrong status in app"
        case .other: return "Other"
        }
    }
}

/// Result of submitting a report — tells the UI whether this report was the
/// one that tipped the connector into an auto-opened maintenance ticket.
struct PlugWatchReportResult: Codable {
    let reportId: UUID
    let unresolvedReports: Int
    let ticketOpened: Bool
    let reliabilityScore: Double
}

struct InsuranceClaim: Identifiable, Codable {
    let id: UUID
    let sessionId: UUID
    let connectorId: UUID
    let reason: String
    let creditAmount: Double
    let createdAt: Date
}

struct WalletEntry: Identifiable, Codable {
    let id: UUID
    let amount: Double
    let reason: String
    let createdAt: Date
}

struct Wallet: Codable {
    let balance: Double
    let entries: [WalletEntry]
}
