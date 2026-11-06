import Foundation
import FoundationModels

/// What a test report needs to say about the phone it ran on.
enum Device {
    /// The model identifier ("iPhone18,1"); in the Simulator, the simulated one.
    static var model: String {
        if let sim = ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] { return sim + " (Simulator)" }
        var u = utsname()
        uname(&u)
        return withUnsafeBytes(of: &u.machine) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
    }

    static var system: String {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        return "iOS \(v.majorVersion).\(v.minorVersion).\(v.patchVersion)"
    }

    static var memory: String {
        String(format: "%.1f GB", Double(ProcessInfo.processInfo.physicalMemory) / 1_073_741_824)
    }

    static var heat: String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "cool"
        case .fair: return "warm"
        case .serious: return "hot"
        case .critical: return "too hot"
        @unknown default: return "unknown"
        }
    }
}

/// Apple's on-device model (Apple Intelligence): PrePro's free, private AI editor on this phone.
enum AppleAI: Equatable {
    case ready
    case turnedOff
    case notThisPhone
    case downloading
    case unavailable(String)

    static func current() -> AppleAI {
        switch SystemLanguageModel.default.availability {
        case .available:
            return .ready
        case .unavailable(let reason):
            switch reason {
            case .appleIntelligenceNotEnabled: return .turnedOff
            case .deviceNotEligible: return .notThisPhone
            case .modelNotReady: return .downloading
            @unknown default: return .unavailable(String(describing: reason))
            }
        @unknown default:
            return .unavailable("unknown")
        }
    }

    var title: String {
        switch self {
        case .ready: return "Ready"
        case .turnedOff: return "Turned off"
        case .notThisPhone: return "Not on this phone"
        case .downloading: return "Getting ready"
        case .unavailable: return "Not available"
        }
    }

    var detail: String {
        switch self {
        case .ready: return "Apple's on-device model can be your free, private AI editor."
        case .turnedOff: return "Turn on Apple Intelligence in Settings to use the free on-device AI editor."
        case .notThisPhone: return "This phone can't run Apple Intelligence. PrePro still edits with its own rules, or with your API key."
        case .downloading: return "The phone is still downloading Apple's model. Try again in a while."
        case .unavailable(let why): return "Apple's model isn't available (\(why))."
        }
    }

    var symbol: String {
        switch self {
        case .ready: return "checkmark.seal.fill"
        case .downloading: return "arrow.down.circle"
        default: return "exclamationmark.circle"
        }
    }
}
