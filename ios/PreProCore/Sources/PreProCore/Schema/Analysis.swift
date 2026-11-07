import Foundation

// What the analysis learned about every file — the same JSON as the desktop's src/prepro/schema/analysis.py and
// media.py. The desktop writes every field (pydantic dumps its defaults), so these decode with Swift's own Codable;
// the iPhone's own analysis (Vision, AVFoundation) fills the same shapes, so both apps decide from the same facts.

public struct Interval: Codable, Equatable, Sendable {
    public var t0: Double
    public var t1: Double
    public var dur: Double { max(0, t1 - t0) }
}

public struct Word: Codable, Equatable, Sendable {
    public var id: String
    public var t0: Double
    public var t1: Double
    public var text: String
    public var conf: Double
    public var filler: Bool
    public var emphasis: Double
}

public struct Segment: Codable, Equatable, Sendable {
    public var id: String
    public var assetId: String
    public var t0: Double
    public var t1: Double
    public var text: String
    public var wordIds: [String]
    public var retakeGroup: String?
    public var retakeRank: Int
    public var falseStart: Bool
    public var fillerRatio: Double
    public var energy: Double
    public var emotion: String?
    public var lang: String?
    public var tags: [String]
    public var speaker: Int?
    public var speakerConf: Double

    enum CodingKeys: String, CodingKey {
        case id, t0, t1, text, energy, emotion, lang, tags, speaker
        case assetId = "asset_id", wordIds = "word_ids", retakeGroup = "retake_group", retakeRank = "retake_rank"
        case falseStart = "false_start", fillerRatio = "filler_ratio", speakerConf = "speaker_conf"
    }
}

public struct Transcript: Codable, Equatable, Sendable {
    public var assetId: String
    public var backend: String
    public var language: String?
    public var words: [Word]
    public var segments: [Segment]
    public var note: String

    enum CodingKeys: String, CodingKey { case backend, language, words, segments, note, assetId = "asset_id" }
}

public struct FaceBox: Codable, Equatable, Sendable {
    public var t: Double
    public var x: Double                       // centre, 0..1
    public var y: Double
    public var w: Double
    public var h: Double
    public var conf: Double
}

public struct Window: Codable, Equatable, Sendable {
    public var t0: Double
    public var t1: Double
    public var score: Double
    public var why: String
}

public struct Seat: Codable, Equatable, Sendable {
    public var x: Double
    public var y: Double
    public var w: Double
    public var h: Double
    public var presence: Double
}

public struct Shot: Codable, Equatable, Sendable {
    public var id: String
    public var assetId: String
    public var t0: Double
    public var t1: Double
    public var keyframes: [Double]
    public var sharpness: Double
    public var brightness: Double
    public var contrast: Double
    public var saturation: Double
    public var shake: Double
    public var motion: Double
    public var cameraMove: String
    public var whipIn: Bool
    public var whipOut: Bool
    public var faces: [FaceBox]
    public var faceRatio: Double
    public var dupGroup: String?
    public var dupRank: Int
    public var quality: Double
    public var aesthetic: Double?
    public var flags: [String]
    public var tags: [String]
    public var desc: String?
    public var shotType: String?
    public var mood: String?
    public var best: [Window]
    public var color: [Double]?
    public var phash: String?
    public var actionPeaks: [Double]
    public var staticRatio: Double
    public var hud: Double
    public var track: [[Double]]
    public var seats: [Seat]
    public var mouth: [[Double]]

    enum CodingKeys: String, CodingKey {
        case id, t0, t1, keyframes, sharpness, brightness, contrast, saturation, shake, motion, faces, quality, aesthetic, flags
        case tags, desc, mood, best, color, phash, hud, track, seats, mouth
        case assetId = "asset_id", cameraMove = "camera_move", whipIn = "whip_in", whipOut = "whip_out", faceRatio = "face_ratio"
        case dupGroup = "dup_group", dupRank = "dup_rank", shotType = "shot_type", actionPeaks = "action_peaks", staticRatio = "static_ratio"
    }

    public var dur: Double { t1 - t0 }
}

public struct AudioReport: Codable, Equatable, Sendable {
    public var lufs: Double?
    public var peakDb: Double?
    public var noiseFloorDb: Double?
    public var snrDb: Double?
    public var clippingRatio: Double
    public var humHz: Double?
    public var wind: Double
    public var echo: Double
    public var speechRatio: Double
    public var issues: [String]

    enum CodingKeys: String, CodingKey {
        case lufs, wind, echo, issues
        case peakDb = "peak_db", noiseFloorDb = "noise_floor_db", snrDb = "snr_db", clippingRatio = "clipping_ratio", humHz = "hum_hz"
        case speechRatio = "speech_ratio"
    }
}

public struct Section: Codable, Equatable, Sendable {
    public var t0: Double
    public var t1: Double
    public var label: String                   // intro | build | drop | break | outro | verse | chorus
    public var energy: Double
}

public struct MusicInfo: Codable, Equatable, Sendable {
    public var bpm: Double
    public var beats: [Double]
    public var downbeats: [Double]
    public var sections: [Section]
    public var energyCurve: [Double]           // 2 Hz, 0..1
    public var key: String?
    public var mode: String?
    public var vocals: Bool?
    public var moodTags: [String]
    public var brightness: Double

    enum CodingKeys: String, CodingKey {
        case bpm, beats, downbeats, sections, key, mode, vocals, brightness
        case energyCurve = "energy_curve", moodTags = "mood_tags"
    }
}

public struct ClipAnalysis: Codable, Equatable, Sendable {
    public var assetId: String
    public var speech: [Interval]
    public var silences: [Interval]
    public var transcript: Transcript?
    public var shots: [Shot]
    public var audio: AudioReport
    public var music: MusicInfo?
    public var place: String?
    public var placeCluster: Int?
    public var dayIndex: Int?
    public var orderKey: Double
    public var facecam: [Double]?
    public var errors: [String]

    enum CodingKeys: String, CodingKey {
        case speech, silences, transcript, shots, audio, music, place, facecam, errors
        case assetId = "asset_id", placeCluster = "place_cluster", dayIndex = "day_index", orderKey = "order_key"
    }
}

public struct GenreGuess: Codable, Equatable, Sendable {
    public var playbook: String
    public var score: Double
    public var why: String
}

public struct GeoPoint: Codable, Equatable, Sendable {
    public var lat: Double
    public var lon: Double
    public var alt: Double?
}

public struct MediaInfo: Codable, Equatable, Sendable {
    public var path: String
    public var size: Int
    public var formatName: String
    public var duration: Double
    public var hasVideo: Bool
    public var hasAudio: Bool
    public var isImage: Bool
    public var width: Int?
    public var height: Int?
    public var fps: Double?
    public var vfr: Bool
    public var rotation: Int
    public var vcodec: String?
    public var acodec: String?
    public var pixFmt: String?
    public var sampleRate: Int?
    public var channels: Int?
    public var bitrate: Int?
    public var creationTime: String?           // ISO 8601 as the file states it ("2026-10-10T08:02:10+05:30", "…Z")
    public var location: GeoPoint?
    public var tags: [String: String]

    enum CodingKeys: String, CodingKey {
        case path, size, duration, width, height, fps, vfr, rotation, vcodec, acodec, channels, bitrate, location, tags
        case formatName = "format_name", hasVideo = "has_video", hasAudio = "has_audio", isImage = "is_image", pixFmt = "pix_fmt"
        case sampleRate = "sample_rate", creationTime = "creation_time"
    }

    /// Width and height as a player shows them (rotation applied).
    public var displaySize: (w: Int, h: Int)? {
        guard let width, let height else { return nil }
        return abs(rotation) % 180 == 90 ? (height, width) : (width, height)
    }

    public var isVertical: Bool { displaySize.map { $0.h > $0.w } ?? false }

    /// The times this file states, for the creator's clock.
    public var clipTimes: ClipTimes { ClipTimes(creationTime: creationTime, tags: tags, isImage: isImage) }
}

public struct Asset: Codable, Equatable, Sendable {
    public var id: String                      // C01, I02, A01 …
    public var path: String                    // relative to the shoot, forward slashes
    public var hash: String
    public var kind: String                    // aroll | broll | screen | voiceover | music | sfx | meme_video | meme_image | image | lut | unknown
    public var kindReason: String
    public var info: MediaInfo
    public var tags: [String]
    public var notes: [String]
    public var userTags: [String]

    enum CodingKeys: String, CodingKey { case id, path, hash, kind, info, tags, notes, kindReason = "kind_reason", userTags = "user_tags" }

    public var name: String { path.split(separator: "/").last.map(String.init) ?? path }
}

public struct ProjectAnalysis: Codable, Equatable, Sendable {
    public var version: Int
    public var root: String
    public var assets: [Asset]
    public var clips: [String: ClipAnalysis]
    public var genres: [GenreGuess]
    public var speechLanguage: String?
    public var stats: [String: Double]
    public var warnings: [String]

    enum CodingKeys: String, CodingKey { case version, root, assets, clips, genres, stats, warnings, speechLanguage = "speech_language" }

    public func asset(_ id: String) -> Asset? { assets.first { $0.id == id } }

    public var allShots: [Shot] { assets.flatMap { clips[$0.id]?.shots ?? [] } }

    public func shot(_ id: String) -> Shot? { allShots.first { $0.id == id } }
}
