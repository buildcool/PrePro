import Foundation

/// A track's fit for the music's job, with the reason.
public struct TrackScore: Equatable, Sendable {
    public var assetId: String
    public var score: Double
    public var why: String
}

/// The music's job (bed / front / light / none) and matching it against the creator's own songs — a port of the
/// desktop's src/prepro/assist/music.py. PrePro never invents a track: it ranks the ones that came with the shoot.
public enum Music {
    static let vocalName = try! NSRegularExpression(
        pattern: #"vocal|song|lyric|feat\.?|ft\.|sing|karaoke|acapella|chorus"#, options: .caseInsensitive)
    static let instrumentalName = try! NSRegularExpression(
        pattern: #"instrumental|inst\b|bgm|beat|lofi|lo-fi|ambient|no vocals?"#, options: .caseInsensitive)

    static func found(_ re: NSRegularExpression, in s: String) -> Bool {
        re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    /// The music's job in a section, from how much of it is speech.
    public static func soundtrackMode(speechCoverage: Double, playbook: Playbook, asmr: Bool = false) -> String {
        let pref = playbook.music["mode"]?.string ?? "mixed"
        if pref == "none" { return "none" }
        if asmr { return "light" }
        if speechCoverage >= 0.5 { return "bed" }
        if speechCoverage <= 0.15 { return pref == "light" ? "light" : "front" }
        return pref == "bed" || pref == "light" ? "bed" : "front"
    }

    /// Whether a song has singing: your tag, else its name, else what the analysis heard.
    public static func hasVocals(_ asset: Asset, _ info: MusicInfo?) -> Bool? {
        if asset.userTags.contains("instrumental") || found(instrumentalName, in: asset.name) { return false }
        if asset.userTags.contains("vocals") || found(vocalName, in: asset.name) { return true }
        return info?.vocals
    }

    /// What the music should be for a job: tempo, energy, mood and the words to search your own library with.
    public static func brief(for mode: String, playbook pb: Playbook, mood: String?, needSecs: Double, pace: Double) -> MusicBrief {
        var prefer = Py.strings(pb.music["prefer"])
        if let mood = Py.text(mood) {
            prefer = [mood] + prefer.filter { $0 != mood }
        }
        var lo = 70.0, hi = 112.0, energy = "low"   // a bed under speech
        switch mode {
        case "bed":
            break
        case "light":
            lo = 60
            hi = 100
        default:
            lo = 90 + 50 * pace
            hi = lo + 45
            energy = ["travel_film", "hype_reel", "teaser"].contains(pb.key) ? "build" : "high"
            if let bpm = pb.music["bpm"]?.array, bpm.count == 2, let a = bpm[0].number, let b = bpm[1].number {
                lo = a                             // a genre with its own tempo (a day in my life: light, 80–125 BPM)
                hi = b
                energy = "medium"
            }
        }
        let first = prefer.first
        let travel = pb.key.contains("travel") || pb.key.contains("vlog") ? "travel" : ""
        var terms = ["\(first ?? "chill") \(mode == "bed" ? "instrumental " : "")\(travel)".trimmingCharacters(in: .whitespacesAndNewlines)]
        if mode == "front" {
            let feel = ["build": "build drop", "high": "energetic"][energy] ?? ""
            terms.append(["\(Int(lo))-\(Int(hi)) bpm", feel, first ?? ""].filter { !$0.isEmpty }.joined(separator: " "))
        }
        if mode == "bed" {
            terms.append("no vocals background music")
        }
        return MusicBrief(mood: first ?? "neutral", energy: energy, bpmMin: lo, bpmMax: hi, genre: "", vocalsOk: mode == "front",
                          structureNeeds: ["at least \(Py.fixed(needSecs, 0))s or loopable"] + (energy == "build" ? ["a clear build → drop"] : []),
                          searchTerms: terms)
    }

    /// Where the song's drop starts, if it has one.
    public static func dropTime(_ m: MusicInfo) -> Double? { m.sections.first { $0.label == "drop" }?.t0 }

    /// Where to start a track so it fits the edit: the drop on a chosen moment, else backtimed to end on the outro,
    /// else the first downbeat.
    public static func bestOffset(_ m: MusicInfo, trackDuration: Double, need: Double, alignDropAt: Double? = nil) -> (offset: Double, why: String) {
        if let at = alignDropAt, let d = dropTime(m), d - at >= 0, d - at + need <= trackDuration + 0.5 {
            return (d - at, "drop lands at \(Py.fixed(at, 1))s")
        }
        if trackDuration > need + 2 && m.sections.contains(where: { $0.label == "outro" }) {
            var off = trackDuration - need
            if !m.downbeats.isEmpty {
                let dist = m.downbeats.map { abs($0 - off) }
                let j = dist.indices.min(by: { dist[$0] < dist[$1] }) ?? 0
                off = m.downbeats[j] + need <= trackDuration + 0.5 ? m.downbeats[j] : off
            }
            return (max(0.0, off), "backtimed to end on the track's outro")
        }
        let first = (m.downbeats.first ?? .infinity) < 4 ? m.downbeats[0] : 0.0
        return (first, "starts on the first downbeat")
    }

    /// The shoot's songs, best fit first (equal scores keep the shoot's order).
    public static func rankTracks(_ pa: ProjectAnalysis, brief: MusicBrief, mode: String, avoid: [String] = [],
                                  exclude: Set<String> = []) -> [TrackScore] {
        let liked = ["chill", "calm", "happy", "upbeat", "epic", "hype", "warm", "aesthetic", "energetic"]
        var out: [TrackScore] = []
        for a in pa.assets where a.kind == "music" && !exclude.contains(a.id) {
            guard let m = pa.clips[a.id]?.music, m.bpm != 0 else { continue }
            let tags = Set(m.moodTags)
            var why: [String] = []
            var s = 0.0
            if tags.contains(brief.mood) {
                s += 0.35
                why.append("mood '\(brief.mood)'")
            }
            let overlap = tags.intersection([brief.mood] + liked.filter { tags.contains($0) })
            s += 0.05 * Double(overlap.count)
            if !tags.isDisjoint(with: avoid) {
                s -= 0.3
                why.append("mood clashes")
            }
            let bpm = m.bpm
            if brief.bpmMin <= bpm && bpm <= brief.bpmMax {
                s += 0.25
                why.append("\(Py.fixed(bpm, 0)) BPM fits")
            } else {
                let d = min(abs(bpm - brief.bpmMin), abs(bpm - brief.bpmMax))
                s += max(-0.2, 0.25 - d / 60)
            }
            if mode == "bed" && hasVocals(a, m) == true {
                s -= 0.45
                why.append("has vocals (bad under speech)")
            }
            if brief.energy == "build" && m.sections.contains(where: { $0.label == "build" || $0.label == "drop" }) {
                s += 0.2
                why.append("has a build → drop")
            }
            let level = Py.mean(m.energyCurve.isEmpty ? [0.5] : m.energyCurve)
            if brief.energy == "low" && level < 0.5 {
                s += 0.15
                why.append("low energy")
            }
            if brief.energy == "high" && level > 0.5 {
                s += 0.15
                why.append("high energy")
            }
            out.append(TrackScore(assetId: a.id, score: Py.round(s, 3), why: why.isEmpty ? "available" : why.joined(separator: ", ")))
        }
        return out.stableSorted { $0.score > $1.score }
    }
}
