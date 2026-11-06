import AVFoundation
import CoreTransferable
import ImageIO
import Photos
import PhotosUI
import PreProCore
import SwiftUI
import UniformTypeIdentifiers

/// A photo or video picked from the library, copied out so its metadata can be read (the original file, not a
/// re-encoded copy: that keeps the capture time and its offset).
struct PickedMedia: Transferable {
    let url: URL
    let isImage: Bool

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .movie) { received in
            PickedMedia(url: try copy(received.file), isImage: false)
        }
        FileRepresentation(importedContentType: .image) { received in
            PickedMedia(url: try copy(received.file), isImage: true)
        }
    }

    static func copy(_ src: URL) throws -> URL {
        let dst = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + "-" + src.lastPathComponent)
        try FileManager.default.copyItem(at: src, to: dst)
        return dst
    }
}

/// The times a file states, read the way the desktop engine reads them: an iPhone video's local creation date (with
/// its offset), the UTC creation time, a photo's EXIF time and offset.
enum MediaTimes {
    static func read(_ media: PickedMedia) async -> ClipTimes {
        media.isImage ? image(media.url) : await video(media.url)
    }

    static func video(_ url: URL) async -> ClipTimes {
        let asset = AVURLAsset(url: url)
        var tags: [String: String] = [:]
        if let items = try? await asset.load(.metadata) {
            for item in items where item.identifier == .quickTimeMetadataCreationDate {
                if let s = try? await item.load(.stringValue) { tags[Clock.appleCreationDate] = s }
            }
        }
        var creation: String?
        if let item = try? await asset.load(.creationDate), let date = try? await item.load(.dateValue) {
            creation = ISO8601DateFormatter().string(from: date)       // UTC, with "Z"
        }
        return ClipTimes(creationTime: creation, tags: tags, isImage: false)
    }

    static func image(_ url: URL) -> ClipTimes {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
              let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any],
              let exif = props[kCGImagePropertyExifDictionary] as? [CFString: Any],
              let when = exif[kCGImagePropertyExifDateTimeOriginal] as? String else { return ClipTimes(isImage: true) }
        let parts = when.split(separator: " ")                          // "2026:10:17 06:42:00"
        guard parts.count == 2 else { return ClipTimes(isImage: true) }
        let day = parts[0].replacingOccurrences(of: ":", with: "-")
        let offset = exif[kCGImagePropertyExifOffsetTimeOriginal] as? String ?? ""
        return ClipTimes(creationTime: "\(day)T\(parts[1])\(offset)", isImage: true)
    }

    /// Where the time came from, in words (for the tester).
    static func source(_ t: ClipTimes) -> String {
        if t.tags[Clock.appleCreationDate] != nil { return "the phone's own local time" }
        if t.isImage, t.creationTime != nil { return "the photo's own time" }
        if t.creationTime != nil { return "UTC, put in this phone's time zone" }
        return "no time in the file"
    }
}

struct ClipRow: Identifiable, Equatable {
    let id = UUID()
    let stamp: String
    let detail: String
    let day: String?
    let date: Date?
}

/// Pick a day of clips and see the time stamps PrePro would put on them: proves on a real iPhone that a Day in my life
/// gets the creator's own times.
struct ClipTimesCheck: View {
    @Binding var rows: [ClipRow]
    @State private var picked: [PhotosPickerItem] = []
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Check your clips' times").font(.headline)
            Text("Pick a few clips from one day. PrePro shows the time stamps it would put on a Day in my life.")
                .font(.subheadline).foregroundStyle(.secondary)
            PhotosPicker(selection: $picked, maxSelectionCount: 30, matching: .any(of: [.videos, .images]),
                         preferredItemEncoding: .current, photoLibrary: .shared()) {
                Label(busy ? "Reading…" : "Choose clips from one day", systemImage: "photo.on.rectangle.angled")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(busy)
            .accessibilityIdentifier("choose-clips")
            .onChange(of: picked) { _, items in
                Task { await read(items) }
            }
            if let summary {
                Text(summary).font(.subheadline.weight(.semibold))
            }
            ForEach(rows) { row in
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(row.stamp).font(.body.monospacedDigit().weight(.semibold)).frame(width: 84, alignment: .leading)
                    Text(row.detail).font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
    }

    /// "One day: 13 clips, 6:42 am to 11:05 pm" — what a Day in my life would be made of.
    var summary: String? {
        let days = Dictionary(grouping: rows.filter { $0.day != nil }, by: { $0.day ?? "" })
        guard let best = days.max(by: { $0.value.count < $1.value.count }), best.value.count >= 2 else { return nil }
        let sorted = best.value.sorted { ($0.date ?? .distantPast) < ($1.date ?? .distantPast) }
        guard let first = sorted.first, let last = sorted.last else { return nil }
        return "\(best.key): \(best.value.count) clips, \(first.stamp) to \(last.stamp)"
    }

    func read(_ items: [PhotosPickerItem]) async {
        busy = true
        defer { busy = false }
        var times: [ClipTimes] = []
        for item in items {
            guard let media = try? await item.loadTransferable(type: PickedMedia.self) else { continue }
            times.append(await MediaTimes.read(media))
            try? FileManager.default.removeItem(at: media.url)          // only the metadata was needed
        }
        let zone = Clock.shootZone(times)
        var out: [ClipRow] = []
        for t in times {
            if let local = Clock.plausible(Clock.localTime(t, zone: zone)) {
                out.append(ClipRow(stamp: Clock.stamp(local), detail: "\(Clock.partOfDay(local)) · \(Clock.shootingDay(local)) · \(MediaTimes.source(t))",
                                   day: Clock.shootingDay(local), date: local.date))
            } else {
                out.append(ClipRow(stamp: "—", detail: MediaTimes.source(t), day: nil, date: nil))
            }
        }
        rows = out.sorted { ($0.date ?? .distantFuture) < ($1.date ?? .distantFuture) }
    }
}
