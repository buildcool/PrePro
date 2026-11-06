import PreProCore
import SwiftUI

/// The start screen of the test builds: which build this is, whether Apple's free AI editor is ready on this phone, a
/// check of the clips' times, and a test report to send back.
struct HomeView: View {
    @State private var ai = AppleAI.current()
    @State private var rows: [ClipRow] = []
    @State private var playbooks = (try? Knowledge.playbooks().count) ?? 0

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Your shoot in. A finished first cut out.")
                            .font(.title2.weight(.bold))
                        Text("This is a test build of PrePro for iPhone. Try the steps below and send the report back.")
                            .font(.subheadline).foregroundStyle(.secondary)
                        Text("Build \(BuildInfo.label)")
                            .font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
                            .accessibilityIdentifier("build-label")
                    }

                    card {
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: ai.symbol).font(.title2).foregroundStyle(ai == .ready ? Color.green : Color.orange)
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Apple Intelligence: \(ai.title)").font(.headline)
                                Text(ai.detail).font(.subheadline).foregroundStyle(.secondary)
                            }
                        }
                    }

                    card { ClipTimesCheck(rows: $rows) }

                    card {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Send test report").font(.headline)
                            Text("The build, this phone, Apple Intelligence and the times above. No photos or videos are included.")
                                .font(.subheadline).foregroundStyle(.secondary)
                            ShareLink(item: report) {
                                Label("Send test report", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.large)
                            .accessibilityIdentifier("send-report")
                        }
                    }

                    Text("Footage never leaves this phone. PrePro's editing rules: \(playbooks) genres loaded.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                .padding(16)
            }
            .navigationTitle("PrePro")
            .onAppear { ai = AppleAI.current() }
        }
    }

    func card<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        content()
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(.background.secondary, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    var report: String {
        var lines = [
            "PrePro for iPhone — test report",
            "Build: \(BuildInfo.label)",
            "Phone: \(Device.model), \(Device.system), \(Device.memory), \(Device.heat)",
            "Apple Intelligence: \(ai.title)",
            "Editing rules: \(playbooks) genres",
        ]
        if rows.isEmpty {
            lines.append("Clip times: not checked")
        } else {
            lines.append("Clip times (\(rows.count)):")
            lines += rows.map { "  \($0.stamp)  \($0.detail)" }
        }
        lines.append("Sent \(Date().formatted(date: .abbreviated, time: .shortened))")
        return lines.joined(separator: "\n")
    }
}
