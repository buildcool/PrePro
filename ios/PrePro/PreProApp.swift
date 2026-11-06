import SwiftUI

@main
struct PreProApp: App {
    var body: some Scene {
        WindowGroup {
            HomeView()
                .tint(.prepro)
        }
    }
}

extension Color {
    /// PrePro's orange (#FF7A1A), the same accent as the desktop app.
    static let prepro = Color(red: 1.0, green: 0.478, blue: 0.102)
}

enum BuildInfo {
    static var version: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?" }
    static var build: String { Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?" }
    /// "0.1.0 (12)": on the start screen and in every test report, so a report names the build it came from.
    static var label: String { "\(version) (\(build))" }
}
