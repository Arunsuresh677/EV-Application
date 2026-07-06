import Foundation

/// Thin REST client. Live session telemetry (kWh/cost ticking up) comes from
/// SessionSocket below, not from polling this client.
final class APIClient {
    static let shared = APIClient()
    private let baseURL = URL(string: "https://api.evplatform.com/v1")!
    private var authToken: String?

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .iso8601WithFractionalSeconds
        return d
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    func setAuthToken(_ token: String) { authToken = token }

    private func request(_ path: String, method: String = "GET", body: Data? = nil, idempotencyKey: String? = nil) async throws -> Data {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        req.httpBody = body
        if let authToken { req.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization") }
        if let idempotencyKey { req.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key") }
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw APIError.badStatus((response as? HTTPURLResponse)?.statusCode ?? -1)
        }
        return data
    }

    func searchStations(lat: Double, lng: Double, radiusKm: Double = 10) async throws -> [Station] {
        let data = try await request("stations/search?lat=\(lat)&lng=\(lng)&radius_km=\(radiusKm)")
        return try decoder.decode([Station].self, from: data)
    }

    func stationDetail(id: UUID) async throws -> Station {
        let data = try await request("stations/\(id.uuidString)")
        return try decoder.decode(Station.self, from: data)
    }

    /// Starting a session must be idempotent — a retried tap (flaky network,
    /// double-tap) must resolve to the same session, never a second charge.
    func startSession(connectorId: UUID, vehicleId: UUID) async throws -> ChargingSession {
        let key = UUID().uuidString   // generate once per user tap and hold it through retries
        let body = try encoder.encode(["connector_id": connectorId.uuidString, "vehicle_id": vehicleId.uuidString])
        let data = try await request("sessions", method: "POST", body: body, idempotencyKey: key)
        return try decoder.decode(ChargingSession.self, from: data)
    }

    func stopSession(id: UUID) async throws -> ChargingSession {
        let data = try await request("sessions/\(id.uuidString)/stop", method: "POST")
        return try decoder.decode(ChargingSession.self, from: data)
    }

    func history(limit: Int = 20) async throws -> [HistoryEntry] {
        let data = try await request("users/me/sessions?limit=\(limit)")
        return try decoder.decode([HistoryEntry].self, from: data)
    }

    // MARK: - Trust Engine+

    func connectorReliability(id: UUID) async throws -> ReliabilityDetail {
        let data = try await request("connectors/\(id.uuidString)/reliability")
        return try decoder.decode(ReliabilityDetail.self, from: data)
    }

    /// Two reports on a connector the network still calls available/occupied
    /// force-flip it to faulted and open a maintenance ticket server-side —
    /// `ticketOpened` on the result tells the UI whether this report was the one.
    func reportIssue(connectorId: UUID, issueType: PlugWatchIssueType, note: String?) async throws -> PlugWatchReportResult {
        struct Body: Encodable { let issueType: String; let note: String? }
        let body = try encoder.encode(Body(issueType: issueType.rawValue, note: note))
        let data = try await request("connectors/\(connectorId.uuidString)/reports", method: "POST", body: body)
        return try decoder.decode(PlugWatchReportResult.self, from: data)
    }

    func wallet() async throws -> Wallet {
        let data = try await request("users/me/credits")
        return try decoder.decode(Wallet.self, from: data)
    }

    func claim(sessionId: UUID) async throws -> InsuranceClaim? {
        do {
            let data = try await request("sessions/\(sessionId.uuidString)/claim")
            return try decoder.decode(InsuranceClaim.self, from: data)
        } catch APIError.badStatus(404) {
            return nil   // no guaranteed-charge failure on this session — the common case
        }
    }
}

enum APIError: Error { case badStatus(Int) }

extension JSONDecoder.DateDecodingStrategy {
    /// Backend timestamps look like "2026-07-06T12:53:29.165Z" — the plain
    /// .iso8601 strategy rejects the fractional seconds, so this variant
    /// tries with-fraction first and falls back to without.
    static let iso8601WithFractionalSeconds = custom { decoder in
        let container = try decoder.singleValueContainer()
        let string = try container.decode(String.self)
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = withFraction.date(from: string) { return date }
        let withoutFraction = ISO8601DateFormatter()
        if let date = withoutFraction.date(from: string) { return date }
        throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid ISO8601 date: \(string)")
    }
}

/// Live session updates arrive over a WebSocket fed by the OCPP Central
/// System's MeterValues stream — REST polling would be too slow (target < 5s lag).
final class SessionSocket: ObservableObject {
    @Published var session: ChargingSession?
    private var task: URLSessionWebSocketTask?

    func connect(sessionId: UUID) {
        let url = URL(string: "wss://api.evplatform.com/ws/sessions/\(sessionId.uuidString)")!
        task = URLSession.shared.webSocketTask(with: url)
        task?.resume()
        listen()
    }

    private func listen() {
        task?.receive { [weak self] result in
            guard let self else { return }
            if case .success(.string(let text)) = result,
               let data = text.data(using: .utf8),
               let session = try? JSONDecoder().decode(ChargingSession.self, from: data) {
                DispatchQueue.main.async { self.session = session }
            }
            self.listen()   // keep listening
        }
    }

    func disconnect() { task?.cancel(with: .goingAway, reason: nil) }
}
