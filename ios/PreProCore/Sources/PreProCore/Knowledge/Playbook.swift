import Foundation
import Yams

/// How a genre is cut: pacing, budgets, captions, music and its signature moves — read from the desktop's own
/// src/prepro/knowledge/playbooks.yaml (bundled unchanged), so the phone and the PC edit by the same rules.
public struct Pacing: Codable, Equatable, Sendable {
    public var arollShot: [Double] = [2, 6]
    public var brollShot: [Double] = [1.5, 4]
    public var tightness: Double = 0.5
    public var breath: Double = 0.12
    public var maxPause: Double = 0.5
    public var deadZone: Double = 10

    enum CodingKeys: String, CodingKey {
        case tightness, breath
        case arollShot = "aroll_shot", brollShot = "broll_shot", maxPause = "max_pause", deadZone = "dead_zone"
    }
}

extension Pacing {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        arollShot = try c.v(.arollShot, [2, 6])
        brollShot = try c.v(.brollShot, [1.5, 4])
        tightness = try c.v(.tightness, 0.5)
        breath = try c.v(.breath, 0.12)
        maxPause = try c.v(.maxPause, 0.5)
        deadZone = try c.v(.deadZone, 10)
    }
}

public struct Playbook: Codable, Equatable, Sendable {
    public var key: String = ""
    public var name: String
    public var aspect: String = "16:9"
    public var target: [Double] = [30, 90]
    public var keepRatio: Double = 0.6
    public var structure: [String] = []
    public var pacing: Pacing = Pacing()
    public var budgets: [String: Double] = [:]
    public var captions: [String: JSONValue] = [:]
    public var music: [String: JSONValue] = [:]
    public var memes: String = "never"
    public var transitions: [String: JSONValue] = [:]
    public var splitEdits: [String: Double] = [:]
    public var signature: [String] = []
    public var donts: [String] = []
    public var hooks: [String] = []

    enum CodingKeys: String, CodingKey {
        case key, name, aspect, target, structure, pacing, budgets, captions, music, memes, transitions, signature, donts, hooks
        case keepRatio = "keep_ratio", splitEdits = "split_edits"
    }

    /// Effects of this kind per minute of finished video (0 when the genre doesn't use it).
    public func budget(_ kind: String) -> Double { budgets[kind] ?? 0 }
}

extension Playbook {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.v(.key, "")
        name = try c.decode(String.self, forKey: .name)
        aspect = try c.v(.aspect, "16:9")
        target = try c.v(.target, [30, 90])
        keepRatio = try c.v(.keepRatio, 0.6)
        structure = try c.v(.structure, [])
        pacing = try c.v(.pacing, Pacing())
        budgets = try c.v(.budgets, [:])
        captions = try c.v(.captions, [:])
        music = try c.v(.music, [:])
        memes = try c.v(.memes, "never")
        transitions = try c.v(.transitions, [:])
        splitEdits = try c.v(.splitEdits, [:])
        signature = try c.v(.signature, [])
        donts = try c.v(.donts, [])
        hooks = try c.v(.hooks, [])
    }
}

public enum KnowledgeError: Error, CustomStringConvertible {
    case missing(String)
    case unknownPlaybook(String)

    public var description: String {
        switch self {
        case .missing(let f): return "knowledge file \(f) is not in the app bundle"
        case .unknownPlaybook(let k): return "no playbook called \(k)"
        }
    }
}

public enum Knowledge {
    /// A bundled knowledge file (playbooks, craft, hooks …) as plain values. Each YAML scalar keeps the type YAML gives
    /// it — so a quoted "off" stays a string, never the YAML 1.1 boolean false.
    public static func load(_ name: String) throws -> JSONValue {
        guard let url = Bundle.module.url(forResource: name, withExtension: "yaml", subdirectory: "knowledge") else {
            throw KnowledgeError.missing("\(name).yaml")
        }
        let text = try String(contentsOf: url, encoding: .utf8)
        guard let node = try Yams.compose(yaml: text) else { return .null }
        return value(node)
    }

    static func value(_ node: Node) -> JSONValue {
        switch node {
        case .scalar(let s):
            if s.style == .singleQuoted || s.style == .doubleQuoted { return .string(s.string) }
            return plain(s.string)
        case .sequence(let seq):
            return .array(seq.map { value($0) })
        case .mapping(let map):
            var out: [String: JSONValue] = [:]
            for (k, v) in map {
                out[k.string ?? String(describing: k)] = value(v)
            }
            return .object(out)
        default:
            return .null
        }
    }

    /// An unquoted YAML scalar, typed the way PyYAML (the desktop's reader) types it: null, YAML 1.1 booleans
    /// (yes/no/on/off/true/false), integers, floats (with a dot), anything else a string.
    static func plain(_ s: String) -> JSONValue {
        if ["", "~", "null", "Null", "NULL"].contains(s) { return .null }
        if ["yes", "Yes", "YES", "true", "True", "TRUE", "on", "On", "ON"].contains(s) { return .bool(true) }
        if ["no", "No", "NO", "false", "False", "FALSE", "off", "Off", "OFF"].contains(s) { return .bool(false) }
        let digits = s.replacingOccurrences(of: "_", with: "")
        if s.range(of: #"^[-+]?(0|[1-9][0-9_]*)$"#, options: .regularExpression) != nil, let i = Int(digits) {
            return .number(Double(i))
        }
        if s.range(of: #"^[-+]?([0-9][0-9_]*)?\.[0-9_]*([eE][-+]?[0-9]+)?$"#, options: .regularExpression) != nil,
           let d = Double(digits) {
            return .number(d)
        }
        return .string(s)
    }

    nonisolated(unsafe) private static var cache: [String: Playbook]?
    private static let lock = NSLock()

    /// Every playbook, by key (story_vlog, photo_reel, day_in_life, text_reel …).
    public static func playbooks() throws -> [String: Playbook] {
        lock.lock()
        defer { lock.unlock() }
        if let cache { return cache }
        guard case .object(let all) = try load("playbooks") else { return [:] }
        var out: [String: Playbook] = [:]
        let decoder = PreProJSON.decoder()
        for (key, raw) in all {
            var pb = try decoder.decode(Playbook.self, from: PreProJSON.encoder().encode(raw))
            pb.key = key
            out[key] = pb
        }
        cache = out
        return out
    }

    public static func playbook(_ key: String) throws -> Playbook {
        guard let pb = try playbooks()[key] else { throw KnowledgeError.unknownPlaybook(key) }
        return pb
    }
}
