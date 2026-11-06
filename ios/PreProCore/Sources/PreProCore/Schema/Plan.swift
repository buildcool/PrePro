import Foundation

// Editorial plans — the same JSON as the desktop's src/prepro/schema/plan.py. Plans reference ids only (segments,
// words, shots, assets); the compiler turns them into frame-exact times.

public struct Knobs: Codable, Equatable, Sendable {
    public var pace: Double = 0.5
    public var effects: String = "balanced"         // clean | balanced | bold
    public var captions: String = "clean"           // off | clean | bold
    public var humour: String = "light"
    public var musicTrack: String?
    public var targetLength: Double?
    public var freedom: String = "balanced"
    public var look: String?
    public var memeFlavour: String = "global"
    public var memeTone: String = "clean"
    public var tightness: Double?
    public var shotLen: Double?
    public var layout: String = "auto"
    public var photoMotion: Bool = true

    enum CodingKeys: String, CodingKey {
        case pace, effects, captions, humour, freedom, look, tightness, layout
        case musicTrack = "music_track", targetLength = "target_length", memeFlavour = "meme_flavour", memeTone = "meme_tone"
        case shotLen = "shot_len", photoMotion = "photo_motion"
    }
}

extension Knobs {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        pace = try c.v(.pace, 0.5)
        effects = try c.v(.effects, "balanced")
        captions = try c.v(.captions, "clean")
        humour = try c.v(.humour, "light")
        musicTrack = try c.decodeIfPresent(String.self, forKey: .musicTrack)
        targetLength = try c.decodeIfPresent(Double.self, forKey: .targetLength)
        freedom = try c.v(.freedom, "balanced")
        look = try c.decodeIfPresent(String.self, forKey: .look)
        memeFlavour = try c.v(.memeFlavour, "global")
        memeTone = try c.v(.memeTone, "clean")
        tightness = try c.decodeIfPresent(Double.self, forKey: .tightness)
        shotLen = try c.decodeIfPresent(Double.self, forKey: .shotLen)
        layout = try c.v(.layout, "auto")
        photoMotion = try c.v(.photoMotion, true)
    }
}

public struct HookOption: Codable, Equatable, Sendable {
    public var id: String
    public var kind: String
    public var refs: [String] = []
    public var textHook: String?
    public var why: String = ""
    public var score: Double = 0

    enum CodingKeys: String, CodingKey { case id, kind, refs, why, score, textHook = "text_hook" }
}

extension HookOption {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decode(String.self, forKey: .kind)
        refs = try c.v(.refs, [])
        textHook = try c.decodeIfPresent(String.self, forKey: .textHook)
        why = try c.v(.why, "")
        score = try c.v(.score, 0)
    }
}

public struct Direction: Codable, Equatable, Sendable {
    public var id: String
    public var playbook: String
    public var name: String
    public var aspect: String = "16:9"
    public var targetMin: Double = 30
    public var targetMax: Double = 60
    public var fitScore: Double = 0
    public var why: String = ""
    public var hooks: [HookOption] = []
    public var outline: [String] = []
    public var knobs: Knobs = Knobs()
    public var coverageGaps: [String] = []
    public var fromBrief: Bool = false

    enum CodingKeys: String, CodingKey {
        case id, playbook, name, aspect, why, hooks, outline, knobs
        case targetMin = "target_min", targetMax = "target_max", fitScore = "fit_score", coverageGaps = "coverage_gaps", fromBrief = "from_brief"
    }
}

extension Direction {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        playbook = try c.decode(String.self, forKey: .playbook)
        name = try c.decode(String.self, forKey: .name)
        aspect = try c.v(.aspect, "16:9")
        targetMin = try c.v(.targetMin, 30)
        targetMax = try c.v(.targetMax, 60)
        fitScore = try c.v(.fitScore, 0)
        why = try c.v(.why, "")
        hooks = try c.v(.hooks, [])
        outline = try c.v(.outline, [])
        knobs = try c.v(.knobs, Knobs())
        coverageGaps = try c.v(.coverageGaps, [])
        fromBrief = try c.v(.fromBrief, false)
    }
}

public struct StoryItem: Codable, Equatable, Sendable {
    public var ref: String
    public var role: String = "body"
    public var t0: Double?
    public var t1: Double?
    public var section: String = "main"
    public var note: String = ""
    public var whole: Bool = false
    public var beats: Int?                          // beat-cut formats: beats of the song this moment holds
}

extension StoryItem {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ref = try c.decode(String.self, forKey: .ref)
        role = try c.v(.role, "body")
        t0 = try c.decodeIfPresent(Double.self, forKey: .t0)
        t1 = try c.decodeIfPresent(Double.self, forKey: .t1)
        section = try c.v(.section, "main")
        note = try c.v(.note, "")
        whole = try c.v(.whole, false)
        beats = try c.decodeIfPresent(Int.self, forKey: .beats)
    }
}

public struct StorySection: Codable, Equatable, Sendable {
    public var name: String
    public var musicMode: String = "bed"            // bed | front | light | none
    public var mood: String?
    public var card: String?

    enum CodingKeys: String, CodingKey { case name, mood, card, musicMode = "music_mode" }
}

extension StorySection {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        musicMode = try c.v(.musicMode, "bed")
        mood = try c.decodeIfPresent(String.self, forKey: .mood)
        card = try c.decodeIfPresent(String.self, forKey: .card)
    }
}

public struct StoryPlan: Codable, Equatable, Sendable {
    public var directionId: String
    public var hookId: String?
    public var items: [StoryItem]
    public var sections: [StorySection] = []
    public var chapters: [String] = []
    public var why: String = ""

    enum CodingKeys: String, CodingKey { case items, sections, chapters, why, directionId = "direction_id", hookId = "hook_id" }
}

extension StoryPlan {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        directionId = try c.decode(String.self, forKey: .directionId)
        hookId = try c.decodeIfPresent(String.self, forKey: .hookId)
        items = try c.v(.items, [])
        sections = try c.v(.sections, [])
        chapters = try c.v(.chapters, [])
        why = try c.v(.why, "")
    }
}

public struct MusicBrief: Codable, Equatable, Sendable {
    public var mood: String = "neutral"
    public var energy: String = "medium"            // low | medium | high | build
    public var bpmMin: Double = 80
    public var bpmMax: Double = 120
    public var genre: String = ""
    public var vocalsOk: Bool = false
    public var structureNeeds: [String] = []
    public var searchTerms: [String] = []

    enum CodingKeys: String, CodingKey {
        case mood, energy, genre
        case bpmMin = "bpm_min", bpmMax = "bpm_max", vocalsOk = "vocals_ok", structureNeeds = "structure_needs", searchTerms = "search_terms"
    }
}

extension MusicBrief {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mood = try c.v(.mood, "neutral")
        energy = try c.v(.energy, "medium")
        bpmMin = try c.v(.bpmMin, 80)
        bpmMax = try c.v(.bpmMax, 120)
        genre = try c.v(.genre, "")
        vocalsOk = try c.v(.vocalsOk, false)
        structureNeeds = try c.v(.structureNeeds, [])
        searchTerms = try c.v(.searchTerms, [])
    }
}

public struct MusicCue: Codable, Equatable, Sendable {
    public var section: String
    public var mode: String = "bed"
    public var trackId: String?
    public var alternatives: [String] = []
    public var brief: MusicBrief = MusicBrief()
    public var why: String = ""
    public var gainDb: Double = 0
    public var offset: Double?                      // the cut was built on this track's beats from here

    enum CodingKeys: String, CodingKey { case section, mode, alternatives, brief, why, offset, trackId = "track_id", gainDb = "gain_db" }
}

extension MusicCue {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        section = try c.decode(String.self, forKey: .section)
        mode = try c.v(.mode, "bed")
        trackId = try c.decodeIfPresent(String.self, forKey: .trackId)
        alternatives = try c.v(.alternatives, [])
        brief = try c.v(.brief, MusicBrief())
        why = try c.v(.why, "")
        gainDb = try c.v(.gainDb, 0)
        offset = try c.decodeIfPresent(Double.self, forKey: .offset)
    }
}

/// An anchored effect: text, zoom, sfx, meme, speed, transition, b-roll … with the reason it's there.
public struct EffectCue: Codable, Equatable, Sendable {
    public var type: String
    public var at: String
    public var asset: String?
    public var value: Double?
    public var text: String?
    public var style: String?
    public var dur: Double?
    public var intent: String?
    public var why: String = ""
    public var confidence: Double = 0.7
    public var position: String?
}

extension EffectCue {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decode(String.self, forKey: .type)
        at = try c.decode(String.self, forKey: .at)
        asset = try c.decodeIfPresent(String.self, forKey: .asset)
        value = try c.decodeIfPresent(Double.self, forKey: .value)
        text = try c.decodeIfPresent(String.self, forKey: .text)
        style = try c.decodeIfPresent(String.self, forKey: .style)
        dur = try c.decodeIfPresent(Double.self, forKey: .dur)
        intent = try c.decodeIfPresent(String.self, forKey: .intent)
        why = try c.v(.why, "")
        confidence = try c.v(.confidence, 0.7)
        position = try c.decodeIfPresent(String.self, forKey: .position)
    }
}

public struct BrollGap: Codable, Equatable, Sendable {
    public var at: String
    public var want: String
    public var searchTerms: [String] = []

    enum CodingKeys: String, CodingKey { case at, want, searchTerms = "search_terms" }
}

extension BrollGap {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        at = try c.decode(String.self, forKey: .at)
        want = try c.decode(String.self, forKey: .want)
        searchTerms = try c.v(.searchTerms, [])
    }
}

public struct PolishPlan: Codable, Equatable, Sendable {
    public var directionId: String
    public var music: [MusicCue] = []
    public var effects: [EffectCue] = []
    public var brollGaps: [BrollGap] = []
    public var voScript: [String] = []
    public var look: String?
    public var notes: [String] = []

    enum CodingKeys: String, CodingKey { case music, effects, look, notes, directionId = "direction_id", brollGaps = "broll_gaps", voScript = "vo_script" }
}

extension PolishPlan {
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        directionId = try c.decode(String.self, forKey: .directionId)
        music = try c.v(.music, [])
        effects = try c.v(.effects, [])
        brollGaps = try c.v(.brollGaps, [])
        voScript = try c.v(.voScript, [])
        look = try c.decodeIfPresent(String.self, forKey: .look)
        notes = try c.v(.notes, [])
    }
}
