import SwiftUI

struct HistoryScreen: View {
    @State private var entries: [HistoryEntry] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                Text("\(entries.count) SESSIONS").font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
                Text("Charging history").font(EVTheme.Font.display(26))
            }
            .padding(20)

            List(entries) { entry in
                HistoryRow(entry: entry).listRowBackground(EVTheme.bgDeep)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
        .background(EVTheme.bgDeep.ignoresSafeArea())
        .task { entries = (try? await APIClient.shared.history()) ?? [] }
    }
}

private struct HistoryRow: View {
    let entry: HistoryEntry

    private var statusColor: Color {
        switch entry.status {
        case .completed: return EVTheme.lime
        case .failed: return EVTheme.red
        case .stoppedRemotely: return EVTheme.amber
        default: return EVTheme.textMuted
        }
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text((entry.startTime ?? entry.endTime ?? Date()).formatted(date: .abbreviated, time: .shortened))
                    .font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
                Text("Connector \(entry.connectorId.uuidString.prefix(8))").font(.system(size: 14, weight: .semibold))
                HStack(spacing: 6) {
                    Text(entry.status.rawValue).font(EVTheme.Font.mono(10)).foregroundColor(statusColor)
                    if let claim = entry.claimAmount {
                        Text("· ₹\(String(format: "%.2f", claim)) credited").font(EVTheme.Font.mono(10)).foregroundColor(EVTheme.lime)
                    }
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text("₹\(String(format: "%.2f", entry.cost ?? 0))").font(EVTheme.Font.mono(15, weight: .bold))
                Text("\(String(format: "%.1f", entry.energyKwh ?? 0)) kWh").font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
            }
        }
    }
}
