import SwiftUI

struct ChargingSessionScreen: View {
    let sessionId: UUID
    let batteryCapacityKwh: Double
    @StateObject private var socket = SessionSocket()
    @State private var claim: InsuranceClaim?

    private var percent: Double {
        guard let s = socket.session, batteryCapacityKwh > 0 else { return 0 }
        return min(s.energyKwh / batteryCapacityKwh, 1.0)
    }

    private var isDone: Bool {
        guard let status = socket.session?.status else { return false }
        return [.completed, .failed, .stoppedRemotely].contains(status)
    }

    var body: some View {
        VStack(spacing: 24) {
            VStack(alignment: .leading, spacing: 2) {
                Text("LIVE SESSION").font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
                Text("Charging").font(EVTheme.Font.display(26))
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            ChargeRing(percent: percent, status: socket.session?.status ?? .pending)
                .frame(width: 230, height: 230)

            HStack(spacing: 10) {
                MiniStat(value: String(format: "%.1f", socket.session?.energyKwh ?? 0), label: "kWh delivered")
                MiniStat(value: "₹\(Int(socket.session?.cost ?? 0))", label: "cost so far")
                MiniStat(value: "\(Int(socket.session?.powerKw ?? 0)) kW", label: "charge rate")
            }

            if socket.session?.status == .failed {
                FailBanner(claim: claim)
            }

            if !isDone {
                Button(role: .destructive) {
                    Task { _ = try? await APIClient.shared.stopSession(id: sessionId) }
                } label: {
                    Text("Stop charging")
                        .frame(maxWidth: .infinity).padding()
                        .background(EVTheme.bgRaise).foregroundColor(EVTheme.textMain)
                        .clipShape(Capsule())
                        .overlay(Capsule().stroke(EVTheme.line))
                }
            }

            Spacer()
        }
        .padding(20)
        .background(EVTheme.bgDeep.ignoresSafeArea())
        .onAppear { socket.connect(sessionId: sessionId) }
        .onDisappear { socket.disconnect() }
        .onChange(of: socket.session?.status) { status in
            guard status == .failed else { return }
            Task { claim = try? await APIClient.shared.claim(sessionId: sessionId) }
        }
    }
}

/// Surfaces the guaranteed-charge insurance outcome — auto-filed server-side
/// the instant a Guaranteed connector's session fails (see
/// backend/app/services/insurance.py). No "file a claim" step for the driver.
private struct FailBanner: View {
    let claim: InsuranceClaim?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("⚠ Station fault").font(.system(size: 14, weight: .bold)).foregroundColor(EVTheme.red)
            if let claim {
                Text("✓ ₹\(String(format: "%.2f", claim.creditAmount)) guaranteed-charge credit issued automatically")
                    .font(EVTheme.Font.body(13)).foregroundColor(EVTheme.lime)
            } else {
                Text("The connector faulted mid-session.").font(EVTheme.Font.body(13)).foregroundColor(EVTheme.textMuted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(EVTheme.red.opacity(0.12))
        .overlay(RoundedRectangle(cornerRadius: EVTheme.Radius.panel).stroke(EVTheme.red))
        .clipShape(RoundedRectangle(cornerRadius: EVTheme.Radius.panel))
    }
}

/// The signature element: a segmented gauge, not a generic progress bar —
/// ticks read like an instrument, matching the web prototype's charge ring.
private struct ChargeRing: View {
    let percent: Double
    let status: SessionStatus

    private var ringColor: Color {
        switch status {
        case .failed: return EVTheme.red
        case .completed, .stoppedRemotely: return EVTheme.lime
        default: return EVTheme.amber
        }
    }

    var body: some View {
        ZStack {
            Circle().stroke(EVTheme.bgRaise, lineWidth: 14)
            Circle()
                .trim(from: 0, to: max(percent, 0.02))
                .stroke(ringColor, style: StrokeStyle(lineWidth: 14, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.easeInOut(duration: 0.6), value: percent)

            VStack(spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 2) {
                    Text("\(Int(percent * 100))").font(EVTheme.Font.mono(44, weight: .bold))
                    Text("%").font(EVTheme.Font.mono(20)).foregroundColor(EVTheme.textMuted)
                }
                Text("● \(status.rawValue.uppercased())").font(EVTheme.Font.mono(11)).foregroundColor(ringColor)
            }
        }
    }
}

private struct MiniStat: View {
    let value: String; let label: String
    var body: some View {
        VStack(spacing: 4) {
            Text(value).font(EVTheme.Font.mono(18, weight: .bold)).foregroundColor(EVTheme.textMain)
            Text(label.uppercased()).font(.system(size: 9)).foregroundColor(EVTheme.textMuted)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 12)
        .background(EVTheme.bgPanel).clipShape(RoundedRectangle(cornerRadius: EVTheme.Radius.element))
        .overlay(RoundedRectangle(cornerRadius: EVTheme.Radius.element).stroke(EVTheme.line))
    }
}
