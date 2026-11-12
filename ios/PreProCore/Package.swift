// swift-tools-version: 6.0
// PreProCore: PrePro's editing brain for the iPhone app — the same decisions as the desktop engine (playbooks, story,
// beat grid, time stamps, cringe checks), with the desktop's knowledge YAML as its single source of truth.
import PackageDescription

let package = Package(
    name: "PreProCore",
    platforms: [.iOS("26.0"), .macOS("15.0")],
    products: [.library(name: "PreProCore", targets: ["PreProCore"])],
    dependencies: [.package(url: "https://github.com/jpsim/Yams.git", from: "5.1.0")],
    targets: [
        // Resources/knowledge is copied from src/prepro/knowledge before every build (see .github/workflows/ios.yml)
        // Resources/text_metrics.json: the bundled fonts' widths, written by scripts/export_parity.py (committed)
        // Resources/places.bin: the desktop's offline place names, packed by scripts/export_places.py before every build
        .target(name: "PreProCore", dependencies: ["Yams"],
                resources: [.copy("Resources/knowledge"), .copy("Resources/text_metrics.json"), .copy("Resources/places.bin")]),
        .testTarget(name: "PreProCoreTests", dependencies: ["PreProCore"], resources: [.copy("Golden")]),
    ],
    swiftLanguageModes: [.v5]
)
