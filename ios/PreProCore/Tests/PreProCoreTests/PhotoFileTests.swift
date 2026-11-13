import AVFoundation
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import PreProCore

/// A photo file reads as the desktop reads it: the EXIF time on the camera's own clock with its offset (else this
/// phone's zone), the GPS, which way up it goes, the pixels as stored (no colour conversion) — and a lossless file
/// measures exactly as the desktop's goldens say.
final class PhotoFileTests: XCTestCase {
    func write(_ pic: PhotoPixels, _ type: UTType, _ props: [CFString: Any] = [:]) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("prepro-\(UUID().uuidString).\(type.preferredFilenameExtension ?? "img")")
        let cg = try XCTUnwrap(pic.cgImage)
        let dest = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, type.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(dest, cg, props as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(dest), "written")
        return url
    }

    func spec(_ w: Int, _ h: Int, seed: Int) -> PictureSynth.Spec {
        .init(w: w, h: h, seed: seed, palette: "beach", shapes: 7, noise: 8, dx: 0, dy: 0, blur: 0, dim: nil, faces: [])
    }

    func testTheTimeThePlaceAndWhichWayUpAreRead() throws {
        let pic = PictureSynth.picture(spec(300, 400, seed: 5))
        let stored = Pillow.upright(pic, orientation: 8)              // a phone keeps it on its side, tagged 6
        let url = try write(stored, .jpeg, [
            kCGImagePropertyOrientation: 6,
            kCGImageDestinationLossyCompressionQuality: 0.95,
            kCGImagePropertyExifDictionary: [kCGImagePropertyExifDateTimeOriginal: "2026:10:10 08:05:31",
                                             kCGImagePropertyExifOffsetTimeOriginal: "+05:30"] as [CFString: Any],
            kCGImagePropertyGPSDictionary: [kCGImagePropertyGPSLatitude: 15.5527, kCGImagePropertyGPSLatitudeRef: "N",
                                            kCGImagePropertyGPSLongitude: 73.7517, kCGImagePropertyGPSLongitudeRef: "E"] as [CFString: Any],
        ])
        defer { try? FileManager.default.removeItem(at: url) }
        let f = try PhotoFile.read(url, zone: TimeZone(identifier: "America/New_York")!)
        XCTAssertEqual([f.width, f.height], [400, 300], "the stored size")
        XCTAssertEqual(f.orientation, 6)
        XCTAssertEqual(f.rotation, 90, "ffprobe's rotation for it")
        XCTAssertEqual(f.creationTime, "2026-10-10T08:05:31+05:30", "the camera's clock and the offset it wrote")
        let loc = try XCTUnwrap(f.location)
        XCTAssertEqual(loc.lat, 15.5527, accuracy: 1e-5)
        XCTAssertEqual(loc.lon, 73.7517, accuracy: 1e-5)
        let up = try f.upright()
        XCTAssertEqual([up.width, up.height], [300, 400], "upright")
        var diff = 0
        for (a, b) in zip(up.pixels, pic.pixels) { diff += abs(Int(a) - Int(b)) }
        XCTAssertLessThan(Double(diff) / Double(pic.pixels.count), 8, "the same picture, the right way up (JPEG is lossy)")
    }

    func testATimeWithoutAnOffsetIsOnThisPhonesClock() {
        let when = "2026:10:10 08:05:31"
        XCTAssertEqual(PhotoFile.captureTime(when, offset: nil, zone: TimeZone(identifier: "Asia/Kolkata")!), "2026-10-10T08:05:31+05:30")
        XCTAssertEqual(PhotoFile.captureTime(when, offset: nil, zone: TimeZone(identifier: "America/New_York")!), "2026-10-10T08:05:31-04:00")
        XCTAssertEqual(PhotoFile.captureTime("2027:01:10 08:05:31", offset: nil, zone: TimeZone(identifier: "Europe/London")!),
                       "2027-01-10T08:05:31+00:00")
        XCTAssertEqual(PhotoFile.captureTime(when, offset: "+0530", zone: .gmt), "2026-10-10T08:05:31+05:30")
        XCTAssertEqual(PhotoFile.captureTime(when, offset: "-03:00", zone: .gmt), "2026-10-10T08:05:31-03:00")
        XCTAssertEqual(PhotoFile.captureTime(when, offset: "soon", zone: TimeZone(identifier: "Asia/Kolkata")!), "2026-10-10T08:05:31+05:30")
        XCTAssertNil(PhotoFile.captureTime("0000:00:00 00:00:00", offset: nil, zone: .gmt), "a camera with no clock set")
        XCTAssertNil(PhotoFile.captureTime(nil, offset: "+05:30", zone: .gmt))
    }

    func testALosslessPhotoMeasuresAsTheDesktopsGoldenSays() throws {
        let c = try XCTUnwrap(try PhotoAnalysisTests.golden([PhotoAnalysisTests.Case].self, "measures.json").first { $0.name == "wide" })
        let pic = PictureSynth.picture(c.picture)
        let url = try write(pic, .png)
        defer { try? FileManager.default.removeItem(at: url) }
        let f = try PhotoFile.read(url)
        XCTAssertNil(f.creationTime, "no EXIF time in this file")
        XCTAssertNil(f.location)
        XCTAssertTrue(try f.upright() == pic, "decoded as stored, to the last value")
        let input = try PhotoShoot.input(url, name: "IMG_0001.PNG")
        XCTAssertEqual(input.thumbnail.fingerprint, c.thumb_fnv, "the desktop's thumbnail from the file")
        XCTAssertEqual(input.faces, [], "no face in a landscape")
        let m = PhotoMeasures.measure(input.thumbnail, faces: [])
        XCTAssertEqual(m.sharpness, c.measures.sharpness)
        XCTAssertEqual(m.phash, c.measures.phash)
        XCTAssertEqual(input.name, "IMG_0001.PNG")
    }

    func testTheFileHashIsTheDesktops() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("prepro-\(UUID().uuidString).bin")
        defer { try? FileManager.default.removeItem(at: url) }
        let count: Int = 3 * 1_048_576 + 5
        var bytes = [UInt8](repeating: 0, count: count)
        for i in 0..<count {
            let v: Int = (i * 7 + 3) % 251
            bytes[i] = UInt8(v)
        }
        try Data(bytes).write(to: url)
        XCTAssertEqual(PhotoFile.fastHash(url), "5dcf4087e500e6bb", "size, the first and the last MiB")
        try Data("not a photo".utf8).write(to: url)
        XCTAssertEqual(PhotoFile.fastHash(url), "d0a463a232cd2e5a")
        XCTAssertThrowsError(try PhotoFile.read(url)) { XCTAssertTrue("\($0)".contains("couldn't read the photo")) }
    }

    func testAPictureFromACGImage() throws {
        let pic = PictureSynth.picture(spec(97, 61, seed: 9))
        let back = try XCTUnwrap(PhotoPixels(cgImage: try XCTUnwrap(pic.cgImage)))
        XCTAssertTrue(back == pic, "drawn back without a change")
    }
}
