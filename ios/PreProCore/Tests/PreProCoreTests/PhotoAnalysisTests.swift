import XCTest
@testable import PreProCore

/// The phone judges a photo by the desktop's numbers, to the bit: the same test photos (scripts/portable_picture.py ↔
/// PictureSynth) turned upright from every way a phone stores them, Pillow's thumbnail, then photo_measures — the
/// burst hash, colour, brightness, contrast, sharpness, flags and the striking score (Golden/photos/measures.json).
final class PhotoAnalysisTests: XCTestCase {
    struct Case: Decodable {
        struct Want: Decodable {
            let phash: String
            let color: [Double]
            let brightness: Double
            let contrast: Double
            let sharpness: Double
            let quality: Double
            let flags: [String]
            let aesthetic: Double
        }

        let name: String
        let picture: PictureSynth.Spec
        let orientation: Int
        let faces: [[Double]]
        let stored: [Int]
        let probe: [[Int]]
        let thumb: [Int]
        let thumb_fnv: String
        let measures: Want
    }

    /// The orientation that stores an upright picture the way `orientation` turns back (stored = upright⁻¹).
    static let storing = [1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 8, 7: 7, 8: 6]

    static func golden<T: Decodable>(_ type: T.Type, _ file: String) throws -> T {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil))
        return try JSONDecoder().decode(T.self, from: Data(contentsOf: dir.appendingPathComponent("photos").appendingPathComponent(file)))
    }

    static func boxes(_ f: [[Double]]) -> [FaceBox] { f.map { FaceBox(t: 0, x: $0[0], y: $0[1], w: $0[2], h: $0[3], conf: 0.99) } }

    /// The test photos, made once for the tests that need them (a debug build makes pixels slowly).
    nonisolated(unsafe) static var made: [PictureSynth.Spec: PhotoPixels] = [:]

    static func picture(_ s: PictureSynth.Spec) -> PhotoPixels {
        if let p = made[s] { return p }
        let p = PictureSynth.picture(s)
        made[s] = p
        return p
    }

    func testTheTestPhotosAreTheDesktops() throws {
        for c in try Self.golden([Case].self, "measures.json") {
            let pic = Self.picture(c.picture)
            XCTAssertEqual([pic.width, pic.height], [c.picture.w, c.picture.h], c.name)
            for p in c.probe {
                let i = (p[1] * pic.width + p[0]) * 3
                XCTAssertEqual(pic.pixels[i..<(i + 3)].map(Int.init), Array(p[2...]), "\(c.name): pixel (\(p[0]), \(p[1]))")
            }
        }
    }

    func testEveryWayAPhoneStoresAPhotoTurnsUpright() throws {
        let pic = PictureSynth.picture(.init(w: 64, h: 48, seed: 3, palette: "cafe", shapes: 7, noise: 8, dx: 0, dy: 0, blur: 0, dim: nil,
                                             faces: [[500, 400, 300]]))
        for o in 1...8 {
            let stored = Pillow.upright(pic, orientation: Self.storing[o]!)
            XCTAssertEqual([stored.width, stored.height], o >= 5 ? [48, 64] : [64, 48], "orientation \(o)")
            XCTAssertTrue(Pillow.upright(stored, orientation: o) == pic, "orientation \(o) turns back upright")
        }
    }

    func testPillowsThumbnailAndTheMeasuresAreTheDesktops() throws {
        for c in try Self.golden([Case].self, "measures.json") {
            let pic = Self.picture(c.picture)
            let stored = Pillow.upright(pic, orientation: Self.storing[c.orientation]!)
            XCTAssertEqual([stored.width, stored.height], c.stored, "\(c.name): stored on its side")
            let up = Pillow.upright(stored, orientation: c.orientation)
            XCTAssertTrue(up == pic, "\(c.name): turned upright")
            let thumb = Pillow.thumbnail(up)
            XCTAssertEqual([thumb.width, thumb.height], c.thumb, "\(c.name): thumbnail size")
            XCTAssertEqual(thumb.fingerprint, c.thumb_fnv, "\(c.name): Pillow's thumbnail, to the bit")
            let m = PhotoMeasures.measure(thumb, faces: Self.boxes(c.faces))
            let w = c.measures
            XCTAssertEqual(m.phash, w.phash, "\(c.name): perceptual hash")
            XCTAssertEqual(m.color, w.color, "\(c.name): colour")
            XCTAssertEqual(m.brightness, w.brightness, "\(c.name): brightness")
            XCTAssertEqual(m.contrast, w.contrast, "\(c.name): contrast")
            XCTAssertEqual(m.sharpness, w.sharpness, "\(c.name): sharpness")
            XCTAssertEqual(m.quality, w.quality, "\(c.name): quality")
            XCTAssertEqual(m.flags, w.flags, "\(c.name): flags")
            // numpy squares a float32 with the C library's powf, which can land one bit off x·x: allow the last digit
            XCTAssertEqual(m.aesthetic, w.aesthetic, accuracy: 0.0011, "\(c.name): striking score")
        }
    }

    func testABurstIsCloseAndOtherPhotosAreNot() throws {
        let cases = try Self.golden([Case].self, "measures.json")
        let hash = Dictionary(uniqueKeysWithValues: cases.map { ($0.name, $0.measures.phash) })
        XCTAssertLessThanOrEqual(PhotoMeasures.distance(hash["tall_face"]!, hash["burst"]!), 12, "a burst's two frames")
        XCTAssertGreaterThan(PhotoMeasures.distance(hash["wide"]!, hash["dark"]!), 12)
        XCTAssertEqual(PhotoMeasures.distance("ffffffffffffffff", "0000000000000000"), 64)
    }

    func testPlacesAreNamedLikeTheDesktop() throws {
        struct Place: Decodable {
            let lat: Double
            let lon: Double
            let name: String?
        }

        XCTAssertTrue(Places.available, "Resources/places.bin is made before the build (scripts/export_places.py)")
        for p in try Self.golden([Place].self, "places.json") {
            XCTAssertEqual(Places.name(lat: p.lat, lon: p.lon), p.name, "(\(p.lat), \(p.lon))")
        }
        XCTAssertEqual(Places.km(GeoPoint(lat: 15.5527, lon: 73.7517, alt: nil), GeoPoint(lat: 15.5527, lon: 73.7517, alt: nil)), 0)
        XCTAssertEqual(Places.km(GeoPoint(lat: 0, lon: 0, alt: nil), GeoPoint(lat: 0, lon: 1, alt: nil)), 111.19, accuracy: 0.01)
    }
}
