import SwiftUI

@main
struct IRentUserApp: App {
    @State private var rentalStore = RentalStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(rentalStore)
        }
    }
}
