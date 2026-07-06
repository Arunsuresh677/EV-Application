package com.evplatform.driver.network

import com.evplatform.driver.model.ChargingSession
import com.evplatform.driver.model.HistoryEntry
import com.evplatform.driver.model.InsuranceClaim
import com.evplatform.driver.model.PlugWatchIssueType
import com.evplatform.driver.model.PlugWatchReportResult
import com.evplatform.driver.model.ReliabilityDetail
import com.evplatform.driver.model.Station
import com.evplatform.driver.model.Wallet
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.UUID

/**
 * Thin REST client. Live session telemetry (kWh/cost ticking up) arrives over
 * SessionSocket below, fed by the OCPP Central System's MeterValues stream —
 * not from polling this client (target < 5s UI lag per the tech spec).
 */
class ApiClient(private val client: OkHttpClient, private val baseUrl: String, private var authToken: String? = null) {

    fun setAuthToken(token: String) { authToken = token }

    private fun requestBuilder(path: String): Request.Builder {
        val builder = Request.Builder().url("$baseUrl/$path")
        authToken?.let { builder.addHeader("Authorization", "Bearer $it") }
        return builder
    }

    suspend fun searchStations(lat: Double, lng: Double, radiusKm: Double = 10.0): List<Station> {
        val req = requestBuilder("stations/search?lat=$lat&lng=$lng&radius_km=$radiusKm").build()
        return execute(req) // deserialize with kotlinx.serialization / Moshi in the real impl
    }

    suspend fun stationDetail(id: UUID): Station {
        val req = requestBuilder("stations/$id").build()
        return execute(req)
    }

    /**
     * Starting a session must be idempotent — a retried tap (flaky network,
     * double-tap) must resolve to the same session, never a second charge.
     * Generate the key once per user tap and hold it through any retry.
     */
    suspend fun startSession(connectorId: UUID, vehicleId: UUID): ChargingSession {
        val idempotencyKey = UUID.randomUUID().toString()
        val body = """{"connector_id":"$connectorId","vehicle_id":"$vehicleId"}"""
            .toRequestBody("application/json".toMediaType())
        val req = requestBuilder("sessions")
            .addHeader("Idempotency-Key", idempotencyKey)
            .post(body)
            .build()
        return execute(req)
    }

    suspend fun stopSession(id: UUID): ChargingSession {
        val req = requestBuilder("sessions/$id/stop").post(ByteArray(0).toRequestBody()).build()
        return execute(req)
    }

    suspend fun history(limit: Int = 20): List<HistoryEntry> {
        val req = requestBuilder("users/me/sessions?limit=$limit").build()
        return execute(req)
    }

    // -------------------------------------------------------------------
    // Trust Engine+ — live reliability scoring, crowdsourced Plug Watch
    // fault reports, and automatic guaranteed-charge insurance payouts.
    // -------------------------------------------------------------------

    suspend fun connectorReliability(connectorId: UUID): ReliabilityDetail {
        val req = requestBuilder("connectors/$connectorId/reliability").build()
        return execute(req)
    }

    /**
     * Two reports on a connector the network still calls available/occupied
     * force-flip it to faulted and open a maintenance ticket server-side —
     * `ticketOpened` on the result tells the UI whether this report was the one.
     */
    suspend fun reportIssue(connectorId: UUID, issueType: PlugWatchIssueType, note: String?): PlugWatchReportResult {
        val noteJson = note?.let { "\"${it.replace("\"", "\\\"")}\"" } ?: "null"
        val body = """{"issue_type":"${issueType.apiValue}","note":$noteJson}"""
            .toRequestBody("application/json".toMediaType())
        val req = requestBuilder("connectors/$connectorId/reports").post(body).build()
        return execute(req)
    }

    suspend fun wallet(): Wallet {
        val req = requestBuilder("users/me/credits").build()
        return execute(req)
    }

    /** Returns null when there's no guaranteed-charge failure on this session — the common case. */
    suspend fun claim(sessionId: UUID): InsuranceClaim? {
        val req = requestBuilder("sessions/$sessionId/claim").build()
        return try {
            execute(req)
        } catch (e: ApiException) {
            if (e.statusCode == 404) null else throw e
        }
    }

    private suspend fun <T> execute(request: Request): T {
        // Wire up with your JSON deserializer of choice (Moshi/kotlinx.serialization).
        // Suspend-wrapped via suspendCancellableCoroutine + Call.enqueue in the real impl.
        // A non-2xx response should throw ApiException(statusCode) so callers
        // like claim() above can distinguish "no claim" (404) from real errors.
        throw NotImplementedError("Wire up HTTP execution + JSON parsing here")
    }
}

class ApiException(val statusCode: Int, message: String? = null) : Exception(message ?: "HTTP $statusCode")

/**
 * Live session updates over WebSocket. REST polling is deliberately not used
 * here — see tech spec §5 for the < 5s live-update latency target.
 */
class SessionSocket(private val client: OkHttpClient, private val wsBaseUrl: String) {
    private var webSocket: WebSocket? = null

    fun connect(sessionId: UUID, onUpdate: (ChargingSession) -> Unit) {
        val request = Request.Builder().url("$wsBaseUrl/ws/sessions/$sessionId").build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                // parse `text` into ChargingSession and invoke onUpdate(session)
            }
        })
    }

    fun disconnect() { webSocket?.close(1000, "done") }
}
