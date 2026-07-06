import SwiftUI

/// Design tokens shared across the app — mirrors the web prototype's palette
/// so driver-web and driver-iOS read as the same product.
enum EVTheme {
    static let bgDeep   = Color(hex: "0B0F14")
    static let bgPanel  = Color(hex: "131A21")
    static let bgRaise  = Color(hex: "1B2530")
    static let line     = Color(hex: "232F3B")
    static let lime     = Color(hex: "B4F461")   // available / go
    static let amber    = Color(hex: "FFB454")   // charging in progress
    static let red      = Color(hex: "FF6B5E")   // fault
    static let textMain = Color(hex: "F2F6F5")
    static let textMuted = Color(hex: "7C8B93")

    enum Font {
        static func display(_ size: CGFloat, weight: SwiftUI.Font.Weight = .semibold) -> SwiftUI.Font {
            .system(size: size, weight: weight, design: .rounded)
        }
        static func mono(_ size: CGFloat, weight: SwiftUI.Font.Weight = .regular) -> SwiftUI.Font {
            .system(size: size, weight: weight, design: .monospaced)
        }
        static func body(_ size: CGFloat, weight: SwiftUI.Font.Weight = .regular) -> SwiftUI.Font {
            .system(size: size, weight: weight, design: .default)
        }
    }

    /// Concentric radius system — mirrors web/static/styles.css exactly, so
    /// driver-web and driver-iOS read as the same shape language. Each step
    /// is the level above it minus that container's own padding, so nested
    /// corners share a center point instead of looking arbitrary. Capsule
    /// shapes (buttons, pills, badges) use SwiftUI's native `Capsule()` —
    /// that's already precisely radius = height/2, no numeric token needed.
    enum Radius {
        static let container: CGFloat = 24  // outermost shells: StationDetailSheet, full-screen cards
        static let panel: CGFloat = 16       // one level in: cards, banners
        static let element: CGFloat = 10     // one level in from a panel: stat boxes, small inputs
    }
}

extension Color {
    init(hex: String) {
        var hexSanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        hexSanitized = hexSanitized.replacingOccurrences(of: "#", with: "")
        var rgb: UInt64 = 0
        Scanner(string: hexSanitized).scanHexInt64(&rgb)
        self.init(
            red: Double((rgb >> 16) & 0xFF) / 255,
            green: Double((rgb >> 8) & 0xFF) / 255,
            blue: Double(rgb & 0xFF) / 255
        )
    }
}

/// Connector / station status used across map pins, station detail, and fleet lists.
/// `faulted` (system/Plug-Watch auto-detected) and `maintenance` (operator's
/// own manual toggle) are technically distinct server-side but shown to
/// drivers under one calm label — they don't need to know which it is, just
/// that it's not available. The operator dashboard keeps the distinction.
enum ConnectorStatus: String, Codable {
    case available, occupied, faulted, reserved, maintenance

    var color: Color {
        switch self {
        case .available: return EVTheme.lime
        case .occupied:  return EVTheme.amber
        case .faulted, .maintenance: return EVTheme.red
        case .reserved:  return EVTheme.textMuted
        }
    }

    var label: String {
        switch self {
        case .available: return "Available"
        case .occupied:  return "Occupied"
        case .faulted, .maintenance: return "Under maintenance"
        case .reserved:  return "Reserved"
        }
    }
}
