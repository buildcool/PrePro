import AVFoundation
import Foundation

/// A photo, measured: what the analysis needs from it — the file's facts, its upright thumbnail (≤ 480 px, Pillow's)
/// and the faces on it.
public struct PhotoInput: Sendable {
    public var name: String                    // its name in the project: "IMG_0001.HEIC"
    public var size: Int
    public var formatName: String
    public var width: Int                      // as stored
    public var height: Int
    public var orientation: Int
    public var creationTime: String?
    public var location: GeoPoint?
    public var hash: String
    public var thumbnail: PhotoPixels
    public var faces: [FaceBox]
}

/// A shoot of photos (and a song) analysed on the phone the way the desktop analyses a folder of them
/// (analyze/pipeline.py, context.py): every photo measured, bursts found (and split where half an hour passes), the
/// creator's days and the places named, the genre guessed — the same ProjectAnalysis, so PreProCore's brain makes the
/// desktop's decisions on it.
public enum PhotoShoot {
    public static let analysisVersion = 13
    public static let contextVersion = 6
    static let retakeWindow = 30.0 * 60

    /// Reads and measures one photo file on the phone: EXIF, the upright thumbnail, faces (Vision).
    public static func input(_ url: URL, name: String? = nil, zone: TimeZone = .current) throws -> PhotoInput {
        let f = try PhotoFile.read(url, zone: zone)
        let thumb = Pillow.thumbnail(try f.upright())
        return PhotoInput(name: name ?? url.lastPathComponent, size: f.size, formatName: f.formatName, width: f.width, height: f.height,
                          orientation: f.orientation, creationTime: f.creationTime, location: f.location, hash: PhotoFile.fastHash(url),
                          thumbnail: thumb, faces: Faces.find(in: thumb))
    }

    /// Listens to a song file the way the desktop does (22.05 kHz mono, the first ten minutes): its asset and analysis.
    public static func song(_ url: URL, name: String? = nil, id: String = "A01") throws -> (asset: Asset, clip: ClipAnalysis) {
        let file = try AVAudioFile(forReading: url)
        let rate = file.fileFormat.sampleRate
        let duration = rate > 0 ? Py.round(Double(file.length) / rate, 3) : 0
        let music = MusicAnalysis.analyze(try AudioDecoder.load(url))
        let path = name ?? url.lastPathComponent
        let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int) ?? 0
        let info = MediaInfo(path: path, size: size, formatName: url.pathExtension.lowercased(), duration: duration, hasVideo: false,
                             hasAudio: true, isImage: false, width: nil, height: nil, fps: nil, vfr: false, rotation: 0, vcodec: nil,
                             acodec: nil, pixFmt: nil, sampleRate: Int(rate), channels: Int(file.fileFormat.channelCount), bitrate: nil,
                             creationTime: nil, location: nil, tags: [:])
        let asset = Asset(id: id, path: path, hash: PhotoFile.fastHash(url), kind: "music", kindReason: "the song you chose", info: info,
                          tags: [], notes: [], userTags: [])
        var clip = emptyClip(id)
        clip.music = music
        clip.silences = [Interval(t0: 0, t1: duration)]
        return (asset, clip)
    }

    static func emptyClip(_ id: String) -> ClipAnalysis {
        ClipAnalysis(assetId: id, speech: [], silences: [], transcript: nil, shots: [],
                     audio: AudioReport(lufs: nil, peakDb: nil, noiseFloorDb: nil, snrDb: nil, clippingRatio: 0, humHz: nil, wind: 0, echo: 0,
                                        speechRatio: 0, issues: []),
                     music: nil, place: nil, placeCluster: nil, dayIndex: nil, orderKey: 0, facecam: nil, errors: [])
    }

    /// The shoot's analysis: the song first (the desktop's scan finds a music folder before the photos), the photos in
    /// name order as I01, I02 …
    public static func analysis(photos: [PhotoInput], music: (asset: Asset, clip: ClipAnalysis)? = nil, deviceZone: TimeZone = .current,
                                now: Date = Date(), seconds: Double = 0) -> ProjectAnalysis {
        var pa = ProjectAnalysis(version: analysisVersion, root: "", assets: [], clips: [:], genres: [], speechLanguage: nil, stats: [:],
                                 warnings: [])
        if let music {
            pa.assets.append(music.asset)
            pa.clips[music.asset.id] = music.clip
        }
        for (k, p) in photos.stableSorted(by: { Py.less($0.name, $1.name) }).enumerated() {
            let id = String(format: "I%02d", k + 1)
            let info = MediaInfo(path: p.name, size: p.size, formatName: p.formatName, duration: 0.04, hasVideo: true, hasAudio: false,
                                 isImage: true, width: p.width, height: p.height, fps: 25.0, vfr: false,
                                 rotation: [3: 180, 6: 90, 8: 270][p.orientation] ?? 0, vcodec: nil, acodec: nil, pixFmt: nil,
                                 sampleRate: nil, channels: nil, bitrate: nil, creationTime: p.creationTime, location: p.location, tags: [:])
            pa.assets.append(Asset(id: id, path: p.name, hash: p.hash, kind: "image", kindReason: "photo", info: info, tags: [], notes: [],
                                   userTags: []))
            var clip = emptyClip(id)
            clip.shots = [shot(id, p, duration: info.duration)]
            pa.clips[id] = clip
        }
        duplicateGroups(&pa, ids: pa.assets.filter { $0.kind == "image" }.map(\.id), maxDist: 12, prefix: "burst")
        clusterContext(&pa, deviceZone: deviceZone, now: now)
        pa.genres = genres(pa)
        pa.stats["context_version"] = Double(contextVersion)
        pa.stats["assets"] = Double(pa.assets.count)
        pa.stats["analysis_seconds"] = Py.round(seconds, 1)
        pa.stats["footage_seconds"] = 0
        return pa
    }

    /// _image_shot's Shot for a measured photo.
    static func shot(_ id: String, _ p: PhotoInput, duration: Double) -> Shot {
        let m = PhotoMeasures.measure(p.thumbnail, faces: p.faces)
        let biggest = p.faces.stableSorted { $0.w * $0.h > $1.w * $1.h }.first
        return Shot(id: "\(id).k0", assetId: id, t0: 0, t1: max(duration, 0), keyframes: [0], sharpness: m.sharpness, brightness: m.brightness,
                    contrast: m.contrast, saturation: 0, shake: 0, motion: 0, cameraMove: "static", whipIn: false, whipOut: false,
                    faces: Array(p.faces.prefix(6)), faceRatio: p.faces.isEmpty ? 0 : 1, dupGroup: nil, dupRank: 0, quality: m.quality,
                    aesthetic: m.aesthetic, flags: m.flags, tags: [], desc: nil, shotType: "still", mood: nil, best: [], color: m.color,
                    phash: m.phash, actionPeaks: [], staticRatio: 0, hud: 0,
                    track: biggest.map { [[0, Py.round($0.x, 3), Py.round($0.y, 3)]] } ?? [], seats: [], mouth: [])
    }

    // MARK: visual.py duplicate_groups

    /// Near-identical shots (a burst of photos) share a group; rank 0 is the one to use (the sharpest, most striking).
    static func duplicateGroups(_ pa: inout ProjectAnalysis, ids: [String], maxDist: Int, prefix: String) {
        var shots: [Shot] = ids.flatMap { pa.clips[$0]?.shots ?? [] }
        let hashed = shots.indices.filter { Py.text(shots[$0].phash) != nil }
        var gid = 0
        for (n, i) in hashed.enumerated() {
            for j in hashed[(n + 1)...] {
                if shots[i].assetId == shots[j].assetId { continue }
                if PhotoMeasures.distance(shots[i].phash ?? "", shots[j].phash ?? "") <= maxDist {
                    let g = Py.text(shots[i].dupGroup) ?? Py.text(shots[j].dupGroup) ?? "\(prefix)\(gid)"
                    if Py.text(shots[i].dupGroup) == nil && Py.text(shots[j].dupGroup) == nil { gid += 1 }
                    shots[i].dupGroup = g
                    shots[j].dupGroup = g
                }
            }
        }
        var order: [String] = []
        var groups: [String: [Int]] = [:]
        for (i, s) in shots.enumerated() {
            guard let g = Py.text(s.dupGroup) else { continue }
            if groups[g] == nil { order.append(g) }
            groups[g, default: []].append(i)
        }
        let photo = prefix == "burst"
        func key(_ s: Shot) -> Double {
            -(s.quality + 0.1 * (s.cameraMove != "static" ? 1 : 0) + (photo ? 0.3 * (s.aesthetic ?? 0) + min(0.3, 0.0005 * s.sharpness) : 0.0))
        }
        for g in order {
            let members = groups[g, default: []].stableSorted { a, b in
                key(shots[a]) != key(shots[b]) ? key(shots[a]) < key(shots[b]) : shots[a].t0 < shots[b].t0
            }
            for (r, i) in members.enumerated() { shots[i].dupRank = r }
        }
        put(shots, into: &pa)
    }

    static func put(_ shots: [Shot], into pa: inout ProjectAnalysis) {
        var by: [String: [Shot]] = [:]
        for s in shots { by[s.assetId, default: []].append(s) }
        for (id, ss) in by { pa.clips[id]?.shots = ss }
    }

    // MARK: context.py split_far_duplicates, cluster_context, guess_genres

    static func instant(_ a: Asset, zone: TimeZone?, deviceZone: TimeZone, now: Date) -> Double? {
        Clock.plausible(Clock.localTime(a.info.clipTimes, zone: zone, deviceZone: deviceZone), now: now)?.date.timeIntervalSince1970
    }

    /// Look-alikes are retakes only within half an hour: a group is split where more than that passes.
    static func splitFarDuplicates(_ pa: inout ProjectAnalysis, deviceZone: TimeZone, now: Date) {
        typealias Member = (asset: String, shot: Int, t: Double?, rank: Int)
        let zone = Clock.shootZone(pa.assets.map(\.info.clipTimes))
        var order: [String] = []
        var groups: [String: [Member]] = [:]
        for a in pa.assets {
            for (k, s) in (pa.clips[a.id]?.shots ?? []).enumerated() {
                guard let g = Py.text(s.dupGroup) else { continue }
                if groups[g] == nil { order.append(g) }
                groups[g, default: []].append((a.id, k, instant(a, zone: zone, deviceZone: deviceZone, now: now), s.dupRank))
            }
        }
        for g in order {
            let members = groups[g, default: []]
            let timed = members.filter { $0.t != nil }.stableSorted { $0.t! < $1.t! }
            var parts: [[Member]] = []
            for m in timed {
                if let last = parts.last?.last, let lt = last.t, m.t! - lt <= retakeWindow {
                    parts[parts.count - 1].append(m)
                } else {
                    parts.append([m])
                }
            }
            if parts.count <= 1 { continue }
            parts[0] += members.filter { $0.t == nil }
            for (k, part0) in parts.enumerated() {
                let part = part0.stableSorted { $0.rank < $1.rank }   // the analysis already ranked the takes
                for (r, m) in part.enumerated() {
                    pa.clips[m.asset]?.shots[m.shot].dupGroup = part.count > 1 ? "\(g).\(k)" : nil
                    pa.clips[m.asset]?.shots[m.shot].dupRank = part.count > 1 ? r : 0
                }
            }
        }
    }

    /// Recording order, shooting days on the creator's clock, and places (towns within 25 km of each other are one).
    static func clusterContext(_ pa: inout ProjectAnalysis, deviceZone: TimeZone, now: Date) {
        splitFarDuplicates(&pa, deviceZone: deviceZone, now: now)
        let vids = pa.assets.filter { ["aroll", "broll", "screen", "image", "unknown"].contains($0.kind) }
        let zone = Clock.shootZone(vids.map(\.info.clipTimes))
        if let zone {
            pa.stats["utc_offset_min"] = Double(zone.secondsFromGMT()) / 60
        } else {
            pa.stats.removeValue(forKey: "utc_offset_min")
        }
        let times = vids.map { a in (a, Clock.plausible(Clock.localTime(a.info.clipTimes, zone: zone, deviceZone: deviceZone), now: now)) }
        let days = Set(times.compactMap { $0.1.map(Clock.shootingDay) }).sorted()
        let dayNo = Dictionary(uniqueKeysWithValues: days.enumerated().map { ($1, $0 + 1) })
        let sorted = times.stableSorted { x, y in
            let a = x.1?.date.timeIntervalSince1970 ?? 1e18, b = y.1?.date.timeIntervalSince1970 ?? 1e18
            return a != b ? a < b : Py.less(x.0.path, y.0.path)
        }
        for (i, (a, t)) in sorted.enumerated() {
            if pa.clips[a.id] == nil { pa.clips[a.id] = emptyClip(a.id) }
            pa.clips[a.id]?.orderKey = t?.date.timeIntervalSince1970 ?? 1e12 + Double(i)
            if let t { pa.clips[a.id]?.dayIndex = dayNo[Clock.shootingDay(t)] }
        }
        var centers: [(GeoPoint, String?)] = []
        for a in vids {
            guard let loc = a.info.location else { continue }
            var k = centers.firstIndex { Places.km($0.0, loc) < 25 }
            if k == nil {
                centers.append((loc, Places.name(lat: loc.lat, lon: loc.lon)))
                k = centers.count - 1
            }
            pa.clips[a.id]?.placeCluster = k
            pa.clips[a.id]?.place = Py.text(centers[k!].1) ?? "Place \(k! + 1)"
        }
        pa.stats["places"] = Double(centers.count)
        pa.stats["days"] = Double(pa.clips.values.map { $0.dayIndex ?? 0 }.max() ?? 0)
    }

    /// guess_genres for a shoot of photos: a photo reel (one photo: your words on it, timed to the music).
    static func genres(_ pa: ProjectAnalysis) -> [GenreGuess] {
        let photos = pa.assets.filter { $0.kind == "image" && pa.clips[$0.id] != nil }
        let music = pa.assets.contains { $0.kind == "music" }
        guard !photos.isEmpty else { return [GenreGuess(playbook: "story_vlog", score: 0.4, why: "default")] }
        let one = photos.count == 1
        let why = (one ? "one photo" : "\(photos.count) photos") + (music ? " and a song" : "")
            + (one ? " — your words on the photo, timed to the music" : " — a photo reel cut on the beat")
        return [GenreGuess(playbook: "photo_reel", score: Py.round(min(1.0, 0.9 + 0.05 * (music ? 1 : 0)), 3), why: why)]
    }
}
