import SwiftUI

@main
struct IRentUserApp: App {
    @State private var rentalStore = RentalStore()
    @State private var locationService = LocationService()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(rentalStore)
                .environment(locationService)
        }
    }
}
