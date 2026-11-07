import Foundation

// The creator's brief — the same JSON as the desktop's src/prepro/schema/brief.py. Hard rules are kept to the letter
// (your lines word for word, "use this song", "no zooms"); preferences steer; the engine fills the rest.

public struct HardRule: Codable, Equatable, Sendable {
    public var kind: String                    // must_include | must_exclude | hook | use_music | text_line | add_text | no_effect …
    public var target: String
    public var anchor: String
    public var value: JSONValue?               // a number, a word, or nothing
    public var arg: [String: JSONValue]
    public var source: String
    public var resolved: Bool
}

public struct Preferences: Codable, Equatable, Sendable {
    public var playbook: String?
    public var aspect: String?
    public var targetLength: Double?
    public var goal: String?
    public var audience: String?
    public var mood: String?
    public var pace: Double?
    public var effects: String?
    public var captions: String?
    public var captionLang: String?
    public var humour: String?
    public var memeFlavour: String?
    public var look: String?
    public var musicMood: String?
    public var references: [String]
    public var outline: [String]
    public var freedom: String
    public var deliverables: [String]

    enum CodingKeys: String, CodingKey {
        case playbook, aspect, goal, audience, mood, pace, effects, captions, humour, look, references, outline, freedom, deliverables
        case targetLength = "target_length", captionLang = "caption_lang", memeFlavour = "meme_flavour", musicMood = "music_mood"
    }
}

public struct OpenQuestion: Codable, Equatable, Sendable {
    public var id: String
    public var text: String
    public var options: [String]
    public var ruleIndex: Int?

    enum CodingKeys: String, CodingKey { case id, text, options, ruleIndex = "rule_index" }
}

public struct CreatorBrief: Codable, Equatable, Sendable {
    public var rawText: String
    public var sources: [String]
    public var rules: [HardRule]
    public var prefs: Preferences
    public var questions: [OpenQuestion]
    public var parsedBy: String

    enum CodingKeys: String, CodingKey { case sources, rules, prefs, questions, rawText = "raw_text", parsedBy = "parsed_by" }

    /// No brief at all: the engine decides everything.
    public static let empty = CreatorBrief(rawText: "", sources: [], rules: [], prefs: Preferences(
        playbook: nil, aspect: nil, targetLength: nil, goal: nil, audience: nil, mood: nil, pace: nil, effects: nil, captions: nil,
        captionLang: nil, humour: nil, memeFlavour: nil, look: nil, musicMood: nil, references: [], outline: [], freedom: "balanced",
        deliverables: []), questions: [], parsedBy: "none")
}
