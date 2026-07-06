import SwiftUI

/// Crowdsourced fault reporting. Two reports on a connector the network
/// still shows as fine auto-flags it and opens a maintenance ticket
/// server-side (see APIClient.reportIssue) — this is the client half of
/// that loop.
struct PlugWatchReportSheet: View {
    let connector: Connector
    @Environment(\.dismiss) private var dismiss

    @State private var issueType: PlugWatchIssueType = .wontCharge
    @State private var note: String = ""
    @State private var isSubmitting = false
    @State private var resultMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Report an issue").font(EVTheme.Font.display(18))
            Text("Two reports on a connector the network still shows as fine will auto-flag it — Plug Watch catches faults the hardware feed misses.")
                .font(EVTheme.Font.body(13)).foregroundColor(EVTheme.textMuted)

            VStack(alignment: .leading, spacing: 6) {
                Text("ISSUE TYPE").font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
                Picker("Issue type", selection: $issueType) {
                    ForEach(PlugWatchIssueType.allCases, id: \.self) { type in
                        Text(type.label).tag(type)
                    }
                }
                .pickerStyle(.menu)
                .tint(EVTheme.textMain)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("DETAILS (OPTIONAL)").font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
                TextEditor(text: $note)
                    .frame(height: 80)
                    .padding(8)
                    .background(EVTheme.bgRaise)
                    .clipShape(RoundedRectangle(cornerRadius: EVTheme.Radius.element))
            }

            if let resultMessage {
                Text(resultMessage).font(EVTheme.Font.body(13)).foregroundColor(EVTheme.lime)
            }

            HStack(spacing: 10) {
                Button("Cancel") { dismiss() }
                    .frame(maxWidth: .infinity).padding()
                    .background(EVTheme.bgRaise).foregroundColor(EVTheme.textMain)
                    .clipShape(Capsule())

                Button {
                    Task { await submit() }
                } label: {
                    Text(isSubmitting ? "Submitting…" : "Submit report")
                        .frame(maxWidth: .infinity).padding()
                        .background(EVTheme.lime).foregroundColor(EVTheme.bgDeep)
                        .clipShape(Capsule())
                }
                .disabled(isSubmitting)
            }
        }
        .padding(20)
        .background(EVTheme.bgPanel.ignoresSafeArea())
    }

    private func submit() async {
        isSubmitting = true
        defer { isSubmitting = false }
        do {
            let result = try await APIClient.shared.reportIssue(
                connectorId: connector.id, issueType: issueType, note: note.isEmpty ? nil : note
            )
            resultMessage = result.ticketOpened
                ? "Reported. Enough Plug Watch reports came in — connector flagged and a maintenance ticket opened."
                : "Thanks — report recorded."
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            dismiss()
        } catch {
            resultMessage = "Could not submit report. Try again."
        }
    }
}
