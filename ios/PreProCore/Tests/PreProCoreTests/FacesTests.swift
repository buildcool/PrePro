import AVFoundation
import XCTest
@testable import PreProCore

/// Vision finds the faces the desktop's detector finds, the same way up: on frames of a real face (Intel's sample
/// video, CC BY 4.0, downloaded by the CI into $PREPRO_FACE_VIDEO), measured like a photo (the 480 px thumbnail), every
/// face the desktop saw has a Vision face on it (Golden/photos/faces.json). Text beside a face depends on it.
final class FacesTests: XCTestCase {
    struct Golden: Decodable {
        struct Frame: Decodable {
            let t: Double
            let size: [Int]
            let boxes: [FaceBox]
        }

        let video: String
        let frames: [Frame]
    }

    func testNoFaceInALandscape() {
        let pic = PictureSynth.picture(.init(w: 480, h: 360, seed: 81, palette: "beach", shapes: 7, noise: 8, dx: 0, dy: 0, blur: 0,
                                             dim: nil, faces: []))
        XCTAssertEqual(Faces.find(in: pic), [])
    }

    func testVisionFindsTheFaceTheDesktopFinds() async throws {
        guard let path = ProcessInfo.processInfo.environment["PREPRO_FACE_VIDEO"], FileManager.default.fileExists(atPath: path) else {
            throw XCTSkip("the face video isn't here (the CI downloads it; set PREPRO_FACE_VIDEO to run this locally)")
        }
        let g = try PhotoAnalysisTests.golden(Golden.self, "faces.json")
        let gen = AVAssetImageGenerator(asset: AVURLAsset(url: URL(fileURLWithPath: path)))
        gen.appliesPreferredTrackTransform = true
        gen.requestedTimeToleranceBefore = .zero
        gen.requestedTimeToleranceAfter = .zero
        for f in g.frames {
            let (cg, _) = try await gen.image(at: CMTime(seconds: f.t, preferredTimescale: 600))
            let thumb = Pillow.thumbnail(try XCTUnwrap(Picture(cgImage: cg)))
            XCTAssertEqual([thumb.width, thumb.height], f.size, "frame at \(f.t) s")
            let found = Faces.find(in: thumb)
            print("FACES t=\(f.t) vision=\(found.map { [$0.x, $0.y, $0.w, $0.h, $0.conf].map { Py.round($0, 3) } }) desktop=\(f.boxes.map { [$0.x, $0.y, $0.w, $0.h].map { Py.round($0, 3) } })")
            for b in f.boxes {
                let near = found.filter { abs($0.x - b.x) < 0.1 && abs($0.y - b.y) < 0.12 }
                XCTAssertFalse(near.isEmpty, "t=\(f.t): the desktop's face at (\(b.x), \(b.y)) — Vision: \(found)")
                if let v = near.first {
                    XCTAssertGreaterThan(v.w / b.w, 0.5, "t=\(f.t): about the same size")
                    XCTAssertLessThan(v.w / b.w, 2.0, "t=\(f.t): about the same size")
                    XCTAssertGreaterThanOrEqual(v.conf, 0.6)
                }
            }
        }
    }
}
