import Foundation

enum SyncError: LocalizedError {
    case invalidBaseURL
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL: "API 位址無效。"
        case .server(let message): message
        }
    }
}

struct InspectionSyncService {
    func upload(
        photo: CapturedPhoto,
        rental: DemoRental,
        imageData: Data,
        baseURL: String
    ) async throws {
        guard let url = URL(string: baseURL)?.appending(path: "v1/mobile-inspections/photos") else {
            throw SyncError.invalidBaseURL
        }

        let boundary = "Boundary-(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30

        var body = Data()
        append("rental_id", rental.id, to: &body, boundary: boundary)
        append("car_id", rental.carID, to: &body, boundary: boundary)
        append("expected_plate", rental.plateNumber, to: &body, boundary: boundary)
        append("stage", photo.stage.rawValue, to: &body, boundary: boundary)
        append("view", photo.view.rawValue, to: &body, boundary: boundary)
        append("recognized_plate", photo.result.plateText ?? "", to: &body, boundary: boundary)
        append("image_sha256", photo.sha256, to: &body, boundary: boundary)
        append("captured_at", ISO8601DateFormatter().string(from: photo.capturedAt), to: &body, boundary: boundary)
        let resultData = try JSONEncoder().encode(photo.result)
        append("local_result_json", String(decoding: resultData, as: UTF8.self), to: &body, boundary: boundary)
        appendFile(imageData, name: "photo", filename: photo.fileName, to: &body, boundary: boundary)
        body.append(Data("--(boundary)--\r\n".utf8))
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            let message = String(decoding: data, as: UTF8.self)
            throw SyncError.server(message.isEmpty ? "無法上傳照片。" : message)
        }
    }

    private func append(_ name: String, _ value: String, to body: inout Data, boundary: String) {
        body.append(Data("--(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"(name)\"\r\n\r\n".utf8))
        body.append(Data("(value)\r\n".utf8))
    }

    private func appendFile(_ data: Data, name: String, filename: String, to body: inout Data, boundary: String) {
        body.append(Data("--(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"(name)\"; filename=\"(filename)\"\r\n".utf8))
        body.append(Data("Content-Type: image/jpeg\r\n\r\n".utf8))
        body.append(data)
        body.append(Data("\r\n".utf8))
    }
}
