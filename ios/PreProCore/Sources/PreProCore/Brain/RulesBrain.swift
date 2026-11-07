import Foundation

public enum BrainError: Error, CustomStringConvertible {
    case notOnPhoneYet(String)

    public var description: String {
        switch self {
        case .notOnPhoneYet(let playbook): return "the \(playbook.replacingOccurrences(of: "_", with: " ")) format isn't on the iPhone yet"
        }
    }
}

/// PrePro's rules engine on the phone — a port of the desktop's src/prepro/brain/basic.py (BasicBrain), format by
/// format, reaching the same decisions from the same analysis (checked against the desktop's goldens). The AI editors
/// refine what it decides; it always works, offline, for free.
public final class RulesBrain {
    public let pa: ProjectAnalysis
    public let brief: CreatorBrief
    let rules: [HardRule]
    let excluded: Set<String>                  // "leave this out"
    let included: Set<String>                  // "keep this"
    let no: Set<String>                        // "no music", "no text", "no loop" …
    var reel: ReelGrid?                        // what a reel's story decided, for its polish

    public init(_ pa: ProjectAnalysis, brief: CreatorBrief = .empty) {
        self.pa = pa
        self.brief = brief
        rules = brief.rules
        excluded = Set(rules.filter { $0.kind == "must_exclude" && !$0.target.isEmpty }.map(\.target))
        included = Set(rules.filter { $0.kind == "must_include" && !$0.target.isEmpty }.map(\.target))
        no = Set(rules.filter { $0.kind == "no_effect" }.map(\.target))
    }

    /// The story: which moments, in what order, for how long — with the reason for each.
    public func story(_ d: Direction) throws -> StoryPlan {
        switch d.playbook {
        case "photo_reel":
            guard let sp = try storyPhotoReel(d) else { throw BrainError.notOnPhoneYet("story_vlog") }   // no photos
            return sp
        default:
            throw BrainError.notOnPhoneYet(d.playbook)
        }
    }

    /// Music, words on screen and effects for a story.
    public func polish(_ d: Direction, story: StoryPlan) throws -> PolishPlan {
        var pp = PolishPlan(directionId: d.id, look: no.contains("look") ? nil : d.knobs.look)
        switch d.playbook {
        case "photo_reel":                         // the photos, the song's beat and your words — nothing else
            try polishPhotoReel(d, story: story, &pp)
            return pp
        default:
            throw BrainError.notOnPhoneYet(d.playbook)
        }
    }

    // MARK: material

    /// Usable photos in the order they were taken: one per burst (the sharpest, most striking), dark or blurry ones
    /// out unless the brief asks for them.
    public func photos() -> [Shot] {
        let imgs = pa.assets.filter { $0.kind == "image" && !(pa.clips[$0.id]?.shots.isEmpty ?? true) }
            .map { (asset: $0, at: Self.instant($0.info.creationTime)) }
            .stableSorted { a, b in a.at != b.at ? a.at < b.at : Py.less(a.asset.path, b.asset.path) }
            .map { $0.asset }
        var out: [Shot] = []
        for a in imgs {
            guard let sh = pa.clips[a.id]?.shots.first else { continue }
            if excluded.contains(a.id) || excluded.contains(sh.id) { continue }
            let forced = included.contains(a.id) || included.contains(sh.id)
            let burstCopy = Py.text(sh.dupGroup) != nil && sh.dupRank > 0
            if !forced && (burstCopy || !Set(sh.flags).isDisjoint(with: ["dark", "blurry"])) { continue }
            out.append(sh)
        }
        return out
    }

    /// A file's moment as a number, for putting things in the order they were shot (no time stated: last).
    static func instant(_ creationTime: String?) -> Double {
        Clock.parse(creationTime)?.time.date.timeIntervalSince1970 ?? .infinity
    }

    /// The creator's own on-screen lines, in order (a "Text:" block, POV lines, quoted lines).
    public func textLines() -> [String] {
        rules.filter { $0.kind == "text_line" }.stableSorted { Self.order($0.value) < Self.order($1.value) }.map(\.target)
    }

    static func order(_ v: JSONValue?) -> Double {
        switch v {
        case .number(let n)?: return n
        case .string(let s)?: return Double(s.trimmingCharacters(in: .whitespaces)) ?? 0
        case .bool(let b)?: return b ? 1 : 0
        default: return 0
        }
    }

    static let genericPlace = try! NSRegularExpression(pattern: #"^Place \d+$"#)
    static let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    /// Words for the cover: the creator's first line, else where and when from the photos' GPS and EXIF
    /// ("Goa · Oct 2026", "Goa → Jaipur"), else nothing (a generic "photo dump" adds nothing).
    public func photoTitle() -> String? {
        let lines = textLines()
        if let first = lines.first { return first }
        if let start = Py.text(rules.first(where: { $0.kind == "add_text" && $0.anchor == "start" })?.target) { return start }
        let shots = photos()
        var places: [String] = []
        for s in shots {
            guard let p = Py.text(pa.clips[s.assetId]?.place), !Music.found(Self.genericPlace, in: p), !places.contains(p) else { continue }
            places.append(p)
        }
        let when = shots.lazy.compactMap { Clock.parse(self.pa.asset($0.assetId)?.info.creationTime)?.time }.first
        let whereText = places.count > 1 ? places.prefix(3).joined(separator: " → ") : (places.first ?? "")
        if !whereText.isEmpty, let when {
            let c = when.calendar.dateComponents([.year, .month], from: when.date)    // the month as the file states it
            return "\(whereText) · \(Self.months[(c.month ?? 1) - 1]) \(c.year ?? 0)"
        }
        return Py.text(whereText)
    }

    // MARK: music

    /// The soundtrack for a music-led cut, picked up front (its structure follows the track): the song your brief
    /// names, else the one you chose, else the best fit.
    func musicPlan(_ d: Direction, need: Double) throws -> (track: String?, music: MusicInfo?) {
        let forced = rules.lazy.filter { $0.kind == "use_music" }.compactMap { Py.text($0.arg["asset"]?.string) }.first
        let pb = try Knowledge.playbook(d.playbook)
        let mb = Music.brief(for: "front", playbook: pb, mood: nil, needSecs: need, pace: d.knobs.pace)
        let ranked = Music.rankTracks(pa, brief: mb, mode: "front", avoid: Py.strings(pb.music["avoid"]))
        let tid = forced ?? Py.text(d.knobs.musicTrack) ?? ranked.first?.assetId
        return (tid, tid.flatMap { pa.clips[$0]?.music })
    }

    /// The song and the beat grid a beat-cut format is cut on: a downbeat at the start of the song's strongest part
    /// (its drop or chorus) that leaves enough music after it.
    func reelGrid(need: Double, playbook: String = "photo_reel") throws -> ReelGrid {
        // a fresh direction, as on the desktop: the grid follows the song your brief names, else the best fit
        let (tid, music) = try musicPlan(Direction(id: "x", playbook: playbook, name: "x", aspect: "9:16"), need: need)
        guard let tid, let m = music, m.beats.count >= 8 else {
            return ReelGrid(track: tid, offset: 0, beat: 0.5, beats: (0..<400).map { Double($0) * 0.5 }, label: nil, bpm: 120)
        }
        let dur = pa.asset(tid)?.info.duration ?? 0
        let downs = m.downbeats.isEmpty ? stride(from: 0, to: m.beats.count, by: 4).map { m.beats[$0] } : m.downbeats
        // a day (or your words) plays the song through to its end: no loop seam halfway through the evening
        let room = playbook == "day_in_life" || playbook == "text_reel" ? need * 1.15 : min(need, 8.0)
        var best: (at: Double, label: String)?
        for sec in m.sections.stableSorted(by: { $0.energy > $1.energy }) {
            if let cand = downs.first(where: { $0 >= sec.t0 - 0.05 }), cand + room <= dur {
                best = (cand, sec.label)
                break
            }
        }
        let start = best?.at ?? downs[0]
        let beats = m.beats.filter { $0 >= start - 1e-3 }.map { Py.round($0 - start, 3) }
        let period = beats.count > 4 ? Py.median(Py.diff(Array(beats.prefix(64)))) : 60.0 / max(60.0, m.bpm)
        return ReelGrid(track: tid, offset: Py.round(start, 3), beat: period, beats: beats, label: best?.label, bpm: m.bpm)
    }
}

/// The song and the beat grid a reel is cut on, and what the story decided on it (for the polish).
public struct ReelGrid: Equatable, Sendable {
    public struct Slot: Equatable, Sendable {
        public var from: Int
        public var to: Int
    }

    public var track: String?
    public var offset: Double                  // where in the song the cut starts, s
    public var beat: Double                    // the song's beat period, s
    public var beats: [Double]                 // beat times from the start of the cut
    public var label: String?                  // the part of the song the cut starts on: drop, chorus …
    public var bpm: Double
    public var k = 2                           // beats a photo
    public var lines: [String] = []
    public var slots: [Slot] = []              // one photo: when each of your lines is up, in beats
    public var end: Int?                       // one photo: the beat the reel ends on

    /// Time of beat j (counted from the start of the cut); past the analysed beats the grid carries on at the tempo.
    public func time(ofBeat j: Int) -> Double {
        if j < beats.count { return beats[j] }
        return (beats.last ?? 0) + Double(j - beats.count + 1) * beat
    }

    /// The part of the song, when it has a name.
    var part: String? { Py.text(label) }
}
