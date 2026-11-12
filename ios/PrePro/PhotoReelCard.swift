import PhotosUI
import PreProCore
import SwiftUI
import UniformTypeIdentifiers

enum ReelError: Error, CustomStringConvertible {
    case nothing

    var description: String { "no cut fits these photos" }
}

/// What the phone made of the creator's photos: the analysis, the cut it chose and the timeline with every decision.
struct ReelResult {
    var analysis: ProjectAnalysis
    var direction: Direction
    var story: StoryPlan
    var timeline: Timeline
    var thumbs: [String: UIImage]                  // asset id → its thumbnail
    var seconds: Double
    var song: String?
}

/// Picks photos and a song, reads and measures every photo on the phone, and cuts the reel with PreProCore — the
/// desktop's own decisions, made here, offline.
@MainActor @Observable
final class ReelMaker {
    var status: String?
    var result: ReelResult?
    var failure: String?
    var busy: Bool { status != nil }

    func make(_ items: [PhotosPickerItem], song: URL?, songName: String?) async {
        result = nil
        failure = nil
        let started = Date()
        var inputs: [PhotoInput] = []
        for (k, item) in items.enumerated() {
            status = "Reading photo \(k + 1) of \(items.count)…"
            guard let media = try? await item.loadTransferable(type: PickedMedia.self) else { continue }
            let url = media.url, name = media.name
            let input = await Task.detached(priority: .userInitiated) { try? PhotoShoot.input(url, name: name) }.value
            try? FileManager.default.removeItem(at: url)               // only its measures are kept
            if let input { inputs.append(input) }
        }
        guard !inputs.isEmpty else {
            failure = "None of those photos could be read."
            status = nil
            return
        }
        var music: (asset: Asset, clip: ClipAnalysis)?
        if let song {
            status = "Listening to the song…"
            music = await Task.detached(priority: .userInitiated) { try? PhotoShoot.song(song, name: songName) }.value
            if music == nil { failure = "The song couldn't be read, so the reel is cut to a steady beat." }
        }
        status = "Cutting the reel…"
        let photos = inputs, tune = music
        let spent = Date().timeIntervalSince(started)
        let made = await Task.detached(priority: .userInitiated) { () -> Result<(ProjectAnalysis, Direction, StoryPlan, Timeline), Error> in
            Result {
                let pa = PhotoShoot.analysis(photos: photos, music: tune, seconds: spent)
                let brain = RulesBrain(pa)
                guard let d = try brain.directions().first else { throw ReelError.nothing }
                let story = try brain.story(d)
                let polish = try brain.polish(d, story: story)
                let tl = try Compiler.compile(pa, direction: d, story: story, polish: polish)
                return (pa, d, story, tl)
            }
        }.value
        switch made {
        case .success(let (pa, d, story, tl)):
            var thumbs: [String: UIImage] = [:]
            for a in pa.assets where a.kind == "image" {
                if let p = photos.first(where: { $0.name == a.path }), let cg = p.thumbnail.cgImage { thumbs[a.id] = UIImage(cgImage: cg) }
            }
            result = ReelResult(analysis: pa, direction: d, story: story, timeline: tl, thumbs: thumbs,
                                seconds: Date().timeIntervalSince(started), song: songName)
        case .failure(let error):
            failure = "The reel couldn't be cut: \(error)"
        }
        status = nil
    }

    /// The reel in words for the test report: what went in, what PrePro decided and why — asset ids instead of file
    /// names, never a photo.
    var report: [String] {
        guard let r = result else { return ["Photo reel: not made"] }
        let pa = r.analysis
        let photos = pa.assets.filter { $0.kind == "image" }
        let shots = photos.compactMap { pa.clips[$0.id]?.shots.first }
        let song = pa.assets.first(where: { $0.kind == "music" })
        var lines: [String] = []
        let length = String(format: "%.1f", r.timeline.duration), took = String(format: "%.1f", r.seconds)
        var head = "Photo reel: \(photos.count) photos in, \(r.story.items.count) shots in the reel, \(length) s"
        if let id = song?.id, let bpm = pa.clips[id]?.music?.bpm {
            head += ", " + String(format: "%.0f", bpm) + " BPM"
        } else {
            head += ", no song"
        }
        lines.append(head + ", made in \(took) s")
        lines.append("Cut: \(r.direction.name) — \(r.direction.why)")
        let order: [String] = r.story.items.map { $0.ref.replacingOccurrences(of: ".k0", with: "") }
        lines.append("Order: " + order.joined(separator: " "))
        let faces: [String] = shots.filter { !$0.faces.isEmpty }.map { "\($0.assetId) \($0.faces.count)" }
        lines.append("Faces: " + faces.joined(separator: ", "))
        var bursts: [String] = []
        for g in Set(shots.compactMap(\.dupGroup)).sorted() {
            bursts.append(shots.filter { $0.dupGroup == g }.map(\.assetId).joined(separator: "+"))
        }
        lines.append("Bursts: " + bursts.joined(separator: ", "))
        let flagged: [String] = shots.filter { !$0.flags.isEmpty }.map { "\($0.assetId) \($0.flags.joined(separator: "/"))" }
        lines.append("Left out as blurry/dark: " + flagged.joined(separator: ", "))
        let days = pa.stats["days"].map { String(format: "%.0f", $0) } ?? "?"
        let zone = pa.stats["utc_offset_min"].map { String(format: "%+.0f min", $0) } ?? "none stated"
        let named = pa.clips.values.contains { $0.place != nil } ? "yes" : "no"
        lines.append("Times: \(days) day(s), zone \(zone), places named: \(named)")
        lines.append("Decisions:")
        for s in r.timeline.suggestions {
            var why = s.reason
            for a in pa.assets { why = why.replacingOccurrences(of: a.path, with: a.id) }
            lines.append("  [\(s.type)] \(why)")
        }
        return lines
    }
}

/// The photo reel card: choose photos and a song, then see the reel PrePro cuts and every decision with its reason.
struct PhotoReelCard: View {
    let maker: ReelMaker
    @State private var picked: [PhotosPickerItem] = []
    @State private var song: URL?
    @State private var songName: String?
    @State private var choosingSong = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Make a photo reel").font(.headline)
            Text("Pick the photos of a day or a trip and a song from Files. PrePro reads them on this phone and cuts the reel on the beat.")
                .font(.subheadline).foregroundStyle(.secondary)
            PhotosPicker(selection: $picked, maxSelectionCount: 40, matching: .images, preferredItemEncoding: .current,
                         photoLibrary: .shared()) {
                Label(picked.isEmpty ? "Choose photos" : "\(picked.count) photos chosen", systemImage: "photo.stack")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .disabled(maker.busy)
            .accessibilityIdentifier("choose-photos")
            Button {
                choosingSong = true
            } label: {
                Label(songName ?? "Choose a song (optional)", systemImage: "music.note").frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .disabled(maker.busy)
            .accessibilityIdentifier("choose-song")
            .fileImporter(isPresented: $choosingSong, allowedContentTypes: [.audio]) { result in
                if case .success(let url) = result, let copy = Self.copyIn(url) {
                    song = copy
                    songName = url.lastPathComponent
                }
            }
            Button {
                Task { await maker.make(picked, song: song, songName: songName) }
            } label: {
                Label(maker.status ?? "Make the reel", systemImage: "wand.and.stars").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(picked.isEmpty || maker.busy)
            .accessibilityIdentifier("make-reel")
            if let failure = maker.failure {
                Text(failure).font(.footnote).foregroundStyle(.orange)
            }
            if let r = maker.result { ReelView(result: r) }
        }
    }

    static func copyIn(_ url: URL) -> URL? {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let dst = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + "-" + url.lastPathComponent)
        do {
            try FileManager.default.copyItem(at: url, to: dst)
            return dst
        } catch {
            return nil
        }
    }
}

/// The reel PrePro cut: the cover with its words, the photos in order, and every decision with its reason.
struct ReelView: View {
    let result: ReelResult

    func asset(_ ref: String) -> String { String(ref.split(separator: ".").first ?? "") }

    var summary: String {
        var s = "\(result.story.items.count) shots · " + String(format: "%.1f", result.timeline.duration) + " s"
        if let song = result.song { s += " · " + song }
        return s
    }

    var body: some View {
        let tl = result.timeline
        let title = tl.items.first { $0.kind == "text" }?.text
        VStack(alignment: .leading, spacing: 10) {
            if let first = result.story.items.first, let img = result.thumbs[asset(first.ref)] {
                ZStack(alignment: .bottom) {
                    Image(uiImage: img).resizable().scaledToFill().frame(maxWidth: .infinity).frame(height: 260).clipped()
                    if let title {
                        Text(title).font(.title3.weight(.bold)).foregroundStyle(.white).shadow(radius: 4).padding(12)
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .accessibilityIdentifier("reel-cover")
            }
            Text(summary).font(.subheadline.weight(.semibold))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(Array(result.story.items.enumerated()), id: \.offset) { _, item in
                        if let img = result.thumbs[asset(item.ref)] {
                            Image(uiImage: img).resizable().scaledToFill().frame(width: 54, height: 96).clipped()
                                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                        }
                    }
                }
            }
            Text("What PrePro decided").font(.subheadline.weight(.semibold))
            ForEach(tl.suggestions, id: \.id) { s in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: s.status == "applied" ? "checkmark.circle.fill" : "circle").foregroundStyle(Color.prepro)
                    Text(s.reason).font(.footnote)
                }
            }
            Text("Preview, export and ✓/✕ on each decision come in the next builds.").font(.footnote).foregroundStyle(.secondary)
        }
    }
}
