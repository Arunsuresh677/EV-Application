import SwiftUI

/// The Trust Engine+ wedge, surfaced everywhere a connector appears: map
/// pins, station detail, session start confirmation. Three tiers mirror the
/// web app's badge logic exactly (see web/static/app.js `trustBadgeHtml`) —
/// Guaranteed (score >= 90, no open Plug Watch report), Good, or Low trust.
struct TrustBadge: View {
    let reliabilityScore: Double
    let guaranteed: Bool

    private var tier: (label: String, color: Color) {
        if guaranteed { return ("Guaranteed", EVTheme.lime) }
        if reliabilityScore >= 75 { return ("Good", EVTheme.amber) }
        return ("Low trust", EVTheme.red)
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(tier.color).frame(width: 6, height: 6)
            Text("\(tier.label) · \(Int(reliabilityScore))")
                .font(EVTheme.Font.mono(11, weight: .semibold))
        }
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background(tier.color.opacity(0.14))
        .overlay(Capsule().stroke(tier.color.opacity(0.6)))
        .clipShape(Capsule())
        .foregroundColor(tier.color)
    }
}

#Preview {
    VStack(spacing: 12) {
        TrustBadge(reliabilityScore: 97, guaranteed: true)
        TrustBadge(reliabilityScore: 82, guaranteed: false)
        TrustBadge(reliabilityScore: 41, guaranteed: false)
    }
    .padding()
    .background(EVTheme.bgDeep)
}
