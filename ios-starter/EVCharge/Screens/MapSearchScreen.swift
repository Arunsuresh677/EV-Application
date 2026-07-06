import SwiftUI
import MapKit

struct MapSearchScreen: View {
    @State private var stations: [Station] = []
    @State private var selectedStation: Station?
    @State private var reportingConnector: Connector?
    @State private var region = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 12.9352, longitude: 77.6146),
        span: MKCoordinateSpan(latitudeDelta: 0.05, longitudeDelta: 0.05)
    )

    var body: some View {
        ZStack(alignment: .bottom) {
            EVTheme.bgDeep.ignoresSafeArea()

            Map(coordinateRegion: $region, annotationItems: stations) { station in
                MapAnnotation(coordinate: CLLocationCoordinate2D(latitude: station.lat, longitude: station.lng)) {
                    StationPin(station: station, isSelected: station.id == selectedStation?.id)
                        .onTapGesture { withAnimation(.spring()) { selectedStation = station } }
                }
            }
            .ignoresSafeArea(edges: .top)

            if let station = selectedStation {
                StationDetailSheet(station: station, onReportIssue: { reportingConnector = $0 })
                    .transition(.move(edge: .bottom))
            }
        }
        .task {
            // Replace with the driver's real location once CoreLocation auth is wired up.
            stations = (try? await APIClient.shared.searchStations(lat: region.center.latitude, lng: region.center.longitude)) ?? []
        }
        .sheet(item: $reportingConnector) { connector in
            PlugWatchReportSheet(connector: connector)
        }
    }
}

private struct StationPin: View {
    let station: Station
    let isSelected: Bool

    private var worstStatus: ConnectorStatus {
        if station.connectors.contains(where: { $0.status == .available }) { return .available }
        if station.connectors.contains(where: { $0.status == .faulted }) { return .faulted }
        return .occupied
    }

    var body: some View {
        Text("₹\(Int(station.pricePerKwh))")
            .font(EVTheme.Font.mono(10, weight: .bold))
            .foregroundColor(EVTheme.bgDeep)
            .padding(isSelected ? 12 : 8)
            .background(Circle().fill(worstStatus.color))
            .scaleEffect(isSelected ? 1.25 : 1.0)
            .shadow(color: .black.opacity(0.4), radius: 6, y: 3)
    }
}

/// Bottom sheet — pricing, connectors, and the "Start charging" CTA that
/// kicks off APIClient.startSession (idempotent, see Networking/APIClient.swift).
private struct StationDetailSheet: View {
    let station: Station
    var onReportIssue: (Connector) -> Void
    @State private var isStarting = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Capsule().fill(EVTheme.line).frame(width: 36, height: 4).frame(maxWidth: .infinity)

            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(station.address.uppercased())
                        .font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
                    Text(station.name).font(EVTheme.Font.display(20))
                }
                Spacer()
                ReliabilityPill(score: station.reliabilityScore)
            }

            HStack(spacing: 10) {
                StatBox(value: "₹\(Int(station.pricePerKwh))", label: "per kWh")
                StatBox(value: "\(Int(station.connectors.map(\.powerKw).max() ?? 0))kW", label: "max speed")
                StatBox(value: "\(station.connectors.filter { $0.status == .available }.count)/\(station.connectors.count)", label: "free now")
            }

            ForEach(station.connectors) { connector in
                ConnectorRow(connector: connector, onReportIssue: { onReportIssue(connector) })
            }

            Button {
                Task {
                    isStarting = true
                    defer { isStarting = false }
                    // vehicleId would come from the driver's saved-vehicle selection
                }
            } label: {
                Text(isStarting ? "Starting…" : "Start charging")
                    .font(.system(size: 15, weight: .semibold))
                    .frame(maxWidth: .infinity).padding()
                    .background(EVTheme.lime).foregroundColor(EVTheme.bgDeep)
                    .clipShape(Capsule())
            }
            .disabled(isStarting)
        }
        .padding(18)
        .background(EVTheme.bgPanel)
        .clipShape(RoundedRectangle(cornerRadius: EVTheme.Radius.container, style: .continuous))
    }
}

private struct ReliabilityPill: View {
    let score: Double
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(EVTheme.lime).frame(width: 6, height: 6)
            Text("\(Int(score))% reliable").font(EVTheme.Font.mono(11))
        }
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background(EVTheme.bgRaise).clipShape(Capsule())
        .foregroundColor(EVTheme.textMuted)
    }
}

private struct StatBox: View {
    let value: String; let label: String
    var body: some View {
        VStack(spacing: 2) {
            Text(value).font(EVTheme.Font.mono(16, weight: .bold)).foregroundColor(EVTheme.textMain)
            Text(label.uppercased()).font(.system(size: 9)).foregroundColor(EVTheme.textMuted)
        }
        .frame(maxWidth: .infinity).padding(10)
        .background(EVTheme.bgRaise).clipShape(RoundedRectangle(cornerRadius: EVTheme.Radius.element))
    }
}

private struct ConnectorRow: View {
    let connector: Connector
    var onReportIssue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(connector.type) · #\(connector.ocppConnectorId)").font(EVTheme.Font.mono(13, weight: .bold))
                    Text("\(Int(connector.powerKw)) kW").font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 6) {
                    HStack(spacing: 6) {
                        Circle().fill(connector.status.color).frame(width: 6, height: 6)
                        Text(connector.status.label).font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
                    }
                    if let score = connector.reliabilityScore {
                        TrustBadge(reliabilityScore: score, guaranteed: connector.guaranteed)
                    }
                }
            }
            Button(action: onReportIssue) {
                Text("🚩 Report an issue").font(EVTheme.Font.mono(11)).foregroundColor(EVTheme.textMuted)
            }
        }
        .padding(.vertical, 10)
        Divider().background(EVTheme.line)
    }
}
