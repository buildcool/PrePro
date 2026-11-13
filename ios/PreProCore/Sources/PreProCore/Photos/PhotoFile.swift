import CoreGraphics
import CryptoKit
import Foundation
import ImageIO

public enum PhotoFileError: Error, CustomStringConvertible {
    case unreadable(String)

    public var description: String {
        switch self {
        case .unreadable(let why): return "couldn't read the photo: \(why)"
        }
    }
}

/// A photo file as the desktop reads one (media/probe.py `photo_exif`, analyze/pipeline.py `_image_shot`): its stored
/// size, which way up it goes, when it was taken on the camera's own clock (with the offset it wrote, else this phone's
/// zone), where (GPS, which never leaves the phone), and its pixels — decoded as stored, without colour conversion
/// (Pillow ignores colour profiles too), then turned upright.
public struct PhotoFile: Sendable {
    public var url: URL
    public var size: Int
    public var formatName: String
    public var width: Int                      // as stored
    public var height: Int
    public var orientation: Int                // EXIF 1…8
    public var creationTime: String?           // "2026-10-10T08:02:10+05:30"
    public var location: GeoPoint?

    /// ffprobe's rotation for the EXIF orientation (media/probe.py EXIF_ROTATION).
    public var rotation: Int { [3: 180, 6: 90, 8: 270][orientation] ?? 0 }

    public static func read(_ url: URL, zone: TimeZone = .current) throws -> PhotoFile {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
              let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any] else {
            throw PhotoFileError.unreadable(url.lastPathComponent)
        }
        let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int) ?? 0
        let type = (CGImageSourceGetType(src) as String?) ?? ""
        let format = type.contains("heic") || type.contains("heif") ? "heif" : (type.contains("jpeg") ? "image2" : type)
        let exif = props[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
        let tiff = props[kCGImagePropertyTIFFDictionary] as? [CFString: Any] ?? [:]
        let when = (exif[kCGImagePropertyExifDateTimeOriginal] as? String) ?? (exif[kCGImagePropertyExifDateTimeDigitized] as? String)
            ?? (tiff[kCGImagePropertyTIFFDateTime] as? String)
        let offset = (exif[kCGImagePropertyExifOffsetTimeOriginal] as? String) ?? (exif[kCGImagePropertyExifOffsetTime] as? String)
        return PhotoFile(url: url, size: size, formatName: format,
                         width: (props[kCGImagePropertyPixelWidth] as? Int) ?? 0, height: (props[kCGImagePropertyPixelHeight] as? Int) ?? 0,
                         orientation: (props[kCGImagePropertyOrientation] as? Int) ?? 1,
                         creationTime: captureTime(when, offset: offset, zone: zone),
                         location: gps(props[kCGImagePropertyGPSDictionary] as? [CFString: Any]))
    }

    /// The EXIF capture time as the desktop writes it: "2026:10:10 08:02:10" with its "+05:30" offset; with no offset
    /// (or a bad one), the camera's clock is taken to be in `zone` (Python's astimezone()).
    static func captureTime(_ when: String?, offset: String?, zone: TimeZone) -> String? {
        guard let when else { return nil }
        let digits = when.trimmingCharacters(in: .whitespaces).split(whereSeparator: { ":- T".contains($0) }).map { Int($0) }
        guard digits.count >= 6, let y = digits[0], let mo = digits[1], let d = digits[2], let h = digits[3], let mi = digits[4],
              let s = digits[5], (1...12).contains(mo), (1...31).contains(d), h < 24, mi < 60, s < 60 else { return nil }
        let stamp = String(format: "%04d-%02d-%02dT%02d:%02d:%02d", y, mo, d, h, mi, s)
        if let off = offset.map({ $0.trimmingCharacters(in: .whitespaces) }), let secs = offsetSeconds(off) {
            return stamp + zoneText(secs)
        }
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = zone
        guard let date = cal.date(from: DateComponents(year: y, month: mo, day: d, hour: h, minute: mi, second: s)) else { return nil }
        return stamp + zoneText(zone.secondsFromGMT(for: date))
    }

    /// "+05:30" → 19800 (strptime's %z: ±HH:MM, ±HHMM, or Z).
    static func offsetSeconds(_ s: String) -> Int? {
        if s == "Z" { return 0 }
        guard let sign = s.first, sign == "+" || sign == "-" else { return nil }
        let body = s.dropFirst().replacingOccurrences(of: ":", with: "")
        guard body.count == 4, let hh = Int(body.prefix(2)), let mm = Int(body.suffix(2)), mm < 60 else { return nil }
        return (sign == "-" ? -1 : 1) * (hh * 3600 + mm * 60)
    }

    static func zoneText(_ secs: Int) -> String {
        let a = abs(secs)
        return String(format: "%@%02d:%02d", secs < 0 ? "-" : "+", a / 3600, (a % 3600) / 60)
    }

    /// Degrees from the GPS block, south and west negative; none for (0, 0) or out of range (probe.py `_exif_gps`).
    static func gps(_ g: [CFString: Any]?) -> GeoPoint? {
        guard let g, var lat = g[kCGImagePropertyGPSLatitude] as? Double, var lon = g[kCGImagePropertyGPSLongitude] as? Double else {
            return nil
        }
        if ((g[kCGImagePropertyGPSLatitudeRef] as? String) ?? "N").uppercased().hasPrefix("S") { lat = -lat }
        if ((g[kCGImagePropertyGPSLongitudeRef] as? String) ?? "E").uppercased().hasPrefix("W") { lon = -lon }
        guard (-90...90).contains(lat), (-180...180).contains(lon), lat != 0 || lon != 0 else { return nil }
        return GeoPoint(lat: lat, lon: lon, alt: nil)
    }

    /// The photo upright at full size, 8-bit RGB (ImageOps.exif_transpose(im).convert("RGB")).
    public func upright() throws -> PhotoPixels {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
              let cg = CGImageSourceCreateImageAtIndex(src, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary) else {
            throw PhotoFileError.unreadable(url.lastPathComponent)
        }
        let w = cg.width, h = cg.height
        // the stored values, as Pillow reads them: draw into the photo's own RGB space (no conversion)
        let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
        let own = cg.colorSpace?.model == .rgb ? cg.colorSpace : nil
        var rgbx = [UInt8](repeating: 0, count: w * h * 4)
        let drawn = rgbx.withUnsafeMutableBytes { raw -> Bool in
            let make = { (space: CGColorSpace) in
                CGContext(data: raw.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: space,
                          bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
            }
            guard let ctx = own.flatMap(make) ?? make(srgb) else { return false }
            ctx.interpolationQuality = .none
            ctx.setBlendMode(.copy)
            ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        guard drawn else { throw PhotoFileError.unreadable("\(url.lastPathComponent): \(w)×\(h)") }
        return rgbx.withUnsafeBufferPointer { Pillow.upright($0, width: w, height: h, stride: 4, orientation: orientation) }
    }

    /// project.py `fast_hash`: SHA-1 of the size and the first and last MiB, 16 hex digits (stable across copies).
    public static func fastHash(_ url: URL, block: Int = 1 << 20) -> String {
        guard let fh = try? FileHandle(forReadingFrom: url) else { return "" }
        defer { try? fh.close() }
        let size = (try? fh.seekToEnd()).map { Int($0) } ?? 0
        var sha = Insecure.SHA1()
        sha.update(data: Data(String(size).utf8))
        try? fh.seek(toOffset: 0)
        sha.update(data: (try? fh.read(upToCount: block)) ?? Data())
        if size > 2 * block {
            try? fh.seek(toOffset: UInt64(size - block))
            sha.update(data: (try? fh.read(upToCount: block)) ?? Data())
        }
        return sha.finalize().map { String(format: "%02x", $0) }.joined().prefix(16).description
    }
}
