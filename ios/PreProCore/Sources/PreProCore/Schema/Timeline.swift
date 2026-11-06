import Foundation

// The compiled, frame-exact edit — the same JSON as the desktop's src/prepro/schema/timeline.py, so a timeline can go
// from the phone to the PC and back. Tracks: V1 main picture, V2 cutaways, V3 overlays, T1 text, A1 dialogue and natural
// sound, A2 music, A3 SFX, A4 ambience.

public struct TransformKey: Codable, Equatable, Sendable {
    public var t: Double
    public var cx: Double = 0.5
    public var cy: Double = 0.5
    public var zoom: Double = 1.0
}

extension TransformKey {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        t = try c.decode(Double.self, forKey: .t)
        cx = try c.v(.cx, 0.5)
        cy = try c.v(.cy, 0.5)
        zoom = try c.v(.zoom, 1.0)
    }
}

public struct Transform: Codable, Equatable, Sendable {
    public var cx: Double = 0.5
    public var cy: Double = 0.5
    public var zoom: Double = 1.0
    public var keys: [TransformKey] = []
    public var fit: Bool = false

    public var isIdentity: Bool { keys.isEmpty && abs(zoom - 1) < 1e-3 && abs(cx - 0.5) < 1e-3 && abs(cy - 0.5) < 1e-3 }

    /// (cx, cy, zoom) at item time t: straight lines between keys, held before the first and after the last.
    public func at(_ t: Double) -> (cx: Double, cy: Double, zoom: Double) {
        guard let first = keys.first, let last = keys.last else { return (cx, cy, zoom) }
        if t <= first.t { return (first.cx, first.cy, first.zoom) }
        for (a, b) in zip(keys, keys.dropFirst()) where t <= b.t {
            let f = (t - a.t) / max(b.t - a.t, 1e-6)
            return (a.cx + (b.cx - a.cx) * f, a.cy + (b.cy - a.cy) * f, a.zoom + (b.zoom - a.zoom) * f)
        }
        return (last.cx, last.cy, last.zoom)
    }
}

extension Transform {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        cx = try c.v(.cx, 0.5)
        cy = try c.v(.cy, 0.5)
        zoom = try c.v(.zoom, 1.0)
        keys = try c.v(.keys, [])
        fit = try c.v(.fit, false)
    }
}

public struct Item: Codable, Equatable, Sendable {
    public var id: String
    public var ref: String?
    public var track: String
    public var kind: String                    // video | audio | image | text | color
    public var assetId: String?
    public var srcIn: Double = 0
    public var srcOut: Double = 0
    public var recIn: Double = 0
    public var speed: Double = 1
    public var link: String?
    public var transform: Transform?
    public var place: [Double]?                // (x, y, w, h) of a layout panel, normalised
    public var gainDb: Double = 0
    public var envelope: [[Double]] = []       // (timeline t, gain dB)
    public var fadeIn: Double = 0
    public var fadeOut: Double = 0
    public var transitionIn: String = "cut"
    public var transitionDur: Double = 0
    public var text: String?
    public var style: String?
    public var position: String?
    public var textY: Double?
    public var textScale: Double?
    public var duration: Double?
    public var role: String?
    public var section: String?
    public var look: String?
    public var suggestionIds: [String] = []
    public var note: String = ""

    enum CodingKeys: String, CodingKey {
        case id, ref, track, kind, speed, link, transform, place, envelope, text, style, position, duration, role, section, look, note
        case assetId = "asset_id", srcIn = "src_in", srcOut = "src_out", recIn = "rec_in", gainDb = "gain_db"
        case fadeIn = "fade_in", fadeOut = "fade_out", transitionIn = "transition_in", transitionDur = "transition_dur"
        case textY = "text_y", textScale = "text_scale", suggestionIds = "suggestion_ids"
    }

    public var recDur: Double {
        if ["text", "image", "color"].contains(kind), let duration { return duration }
        return max(0, (srcOut - srcIn) / max(speed, 1e-6))
    }

    public var recOut: Double { recIn + recDur }
}

extension Item {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        ref = try c.decodeIfPresent(String.self, forKey: .ref)
        track = try c.decode(String.self, forKey: .track)
        kind = try c.decode(String.self, forKey: .kind)
        assetId = try c.decodeIfPresent(String.self, forKey: .assetId)
        srcIn = try c.v(.srcIn, 0)
        srcOut = try c.v(.srcOut, 0)
        recIn = try c.v(.recIn, 0)
        speed = try c.v(.speed, 1)
        link = try c.decodeIfPresent(String.self, forKey: .link)
        transform = try c.decodeIfPresent(Transform.self, forKey: .transform)
        place = try c.decodeIfPresent([Double].self, forKey: .place)
        gainDb = try c.v(.gainDb, 0)
        envelope = try c.v(.envelope, [])
        fadeIn = try c.v(.fadeIn, 0)
        fadeOut = try c.v(.fadeOut, 0)
        transitionIn = try c.v(.transitionIn, "cut")
        transitionDur = try c.v(.transitionDur, 0)
        text = try c.decodeIfPresent(String.self, forKey: .text)
        style = try c.decodeIfPresent(String.self, forKey: .style)
        position = try c.decodeIfPresent(String.self, forKey: .position)
        textY = try c.decodeIfPresent(Double.self, forKey: .textY)
        textScale = try c.decodeIfPresent(Double.self, forKey: .textScale)
        duration = try c.decodeIfPresent(Double.self, forKey: .duration)
        role = try c.decodeIfPresent(String.self, forKey: .role)
        section = try c.decodeIfPresent(String.self, forKey: .section)
        look = try c.decodeIfPresent(String.self, forKey: .look)
        suggestionIds = try c.v(.suggestionIds, [])
        note = try c.v(.note, "")
    }
}

public struct CaptionWord: Codable, Equatable, Sendable {
    public var text: String
    public var t0: Double
    public var t1: Double
    public var emph: Bool = false
}

extension CaptionWord {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        text = try c.decode(String.self, forKey: .text)
        t0 = try c.decode(Double.self, forKey: .t0)
        t1 = try c.decode(Double.self, forKey: .t1)
        emph = try c.v(.emph, false)
    }
}

public struct Caption: Codable, Equatable, Sendable {
    public var id: String
    public var t0: Double
    public var t1: Double
    public var words: [CaptionWord]
    public var style: String = "normal"
    public var pos: String = "lower"

    public var text: String { words.map(\.text).joined(separator: " ") }
}

extension Caption {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        t0 = try c.decode(Double.self, forKey: .t0)
        t1 = try c.decode(Double.self, forKey: .t1)
        words = try c.v(.words, [])
        style = try c.v(.style, "normal")
        pos = try c.v(.pos, "lower")
    }
}

public struct Marker: Codable, Equatable, Sendable {
    public var t: Double
    public var name: String
    public var note: String = ""
    public var color: String = "blue"
    public var suggestionId: String?

    enum CodingKeys: String, CodingKey { case t, name, note, color, suggestionId = "suggestion_id" }
}

extension Marker {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        t = try c.decode(Double.self, forKey: .t)
        name = try c.decode(String.self, forKey: .name)
        note = try c.v(.note, "")
        color = try c.v(.color, "blue")
        suggestionId = try c.decodeIfPresent(String.self, forKey: .suggestionId)
    }
}

/// One editing decision, with its reason — the creator can keep or reject each one in the review.
public struct Suggestion: Codable, Equatable, Sendable {
    public var id: String
    public var type: String
    public var status: String = "applied"      // applied | optional | rejected
    public var confidence: Double = 0.8
    public var reason: String
    public var source: String = "rules"
    public var t: Double?
    public var itemIds: [String] = []
    public var payload: [String: JSONValue] = [:]
    public var alternatives: [String] = []
    public var lint: [String] = []

    enum CodingKeys: String, CodingKey { case id, type, status, confidence, reason, source, t, payload, alternatives, lint, itemIds = "item_ids" }

    /// The key the review uses to keep or reject this decision ("stamps", "shot:C12.k0", …).
    public var key: String? { payload["key"]?.string }
}

extension Suggestion {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        type = try c.decode(String.self, forKey: .type)
        status = try c.v(.status, "applied")
        confidence = try c.v(.confidence, 0.8)
        reason = try c.decode(String.self, forKey: .reason)
        source = try c.v(.source, "rules")
        t = try c.decodeIfPresent(Double.self, forKey: .t)
        itemIds = try c.v(.itemIds, [])
        payload = try c.v(.payload, [:])
        alternatives = try c.v(.alternatives, [])
        lint = try c.v(.lint, [])
    }
}

public struct MusicSpan: Codable, Equatable, Sendable {
    public var t0: Double
    public var t1: Double
    public var mode: String
    public var section: String = ""
}

extension MusicSpan {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        t0 = try c.decode(Double.self, forKey: .t0)
        t1 = try c.decode(Double.self, forKey: .t1)
        mode = try c.decode(String.self, forKey: .mode)
        section = try c.v(.section, "")
    }
}

public struct Timeline: Codable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var directionId: String
    public var playbook: String
    public var fps: Double = 30
    public var width: Int = 1920
    public var height: Int = 1080
    public var items: [Item] = []
    public var captions: [Caption] = []
    public var markers: [Marker] = []
    public var suggestions: [Suggestion] = []
    public var musicSpans: [MusicSpan] = []
    public var look: String?
    public var meta: [String: JSONValue] = [:]

    enum CodingKeys: String, CodingKey {
        case id, name, playbook, fps, width, height, items, captions, markers, suggestions, look, meta
        case directionId = "direction_id", musicSpans = "music_spans"
    }

    public var duration: Double {
        items.filter { ["V", "A", "T"].contains($0.track.prefix(1)) }.map(\.recOut).max() ?? 0
    }

    public var aspect: String {
        let w = Double(width), h = Double(height)
        if h > w { return abs(w / h - 9.0 / 16.0) < 0.02 ? "9:16" : "\(width):\(height)" }
        return abs(w / h - 16.0 / 9.0) < 0.02 ? "16:9" : "\(width):\(height)"
    }

    public func track(_ name: String) -> [Item] { items.filter { $0.track == name }.sorted { $0.recIn < $1.recIn } }

    public func tracks() -> [String] {
        let order: [Character: Int] = ["V": 0, "T": 1, "A": 2]
        return Set(items.map(\.track)).sorted { (order[$0.first ?? "Z"] ?? 9, $0) < (order[$1.first ?? "Z"] ?? 9, $1) }
    }
}

extension Timeline {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        directionId = try c.decode(String.self, forKey: .directionId)
        playbook = try c.decode(String.self, forKey: .playbook)
        fps = try c.v(.fps, 30)
        width = try c.v(.width, 1920)
        height = try c.v(.height, 1080)
        items = try c.v(.items, [])
        captions = try c.v(.captions, [])
        markers = try c.v(.markers, [])
        suggestions = try c.v(.suggestions, [])
        musicSpans = try c.v(.musicSpans, [])
        look = try c.decodeIfPresent(String.self, forKey: .look)
        meta = try c.v(.meta, [:])
    }
}
