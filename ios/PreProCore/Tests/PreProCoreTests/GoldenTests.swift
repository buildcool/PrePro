import XCTest
@testable import PreProCore

/// Timelines, stories and polish plans the desktop engine made (scripts/export_parity.py) read the same on the phone:
/// the duration, the tracks, every cut, every word on screen and every review decision, and they write back unchanged.
final class GoldenTests: XCTestCase {
    struct Expect: Decodable {
        let playbook: String
        let duration: Double
        let width: Int
        let height: Int
        let tracks: [String: Int]
        let v1_rec_in: [Double]
        let texts: [String]
        let suggestion_keys: [String]
    }

    func golden(_ name: String, _ file: String) throws -> Data {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil), "Golden folder not bundled")
        return try Data(contentsOf: dir.appendingPathComponent(name).appendingPathComponent(file))
    }

    func testDesktopTimelinesReadTheSame() throws {
        for name in ["photo_reel", "day_in_life", "text_reel"] {
            let tl = try PreProJSON.decoder().decode(Timeline.self, from: golden(name, "timeline.json"))
            let want = try JSONDecoder().decode(Expect.self, from: golden(name, "expect.json"))
            XCTAssertEqual(tl.playbook, want.playbook, name)
            XCTAssertEqual(tl.duration, want.duration, accuracy: 0.002, name)
            XCTAssertEqual(tl.width, want.width, name)
            XCTAssertEqual(tl.height, want.height, name)
            XCTAssertEqual(tl.aspect, "9:16", name)
            XCTAssertEqual(Dictionary(uniqueKeysWithValues: tl.tracks().map { ($0, tl.track($0).count) }), want.tracks, name)
            let cuts = tl.track("V1").map(\.recIn)
            XCTAssertEqual(cuts.count, want.v1_rec_in.count, name)
            for (got, exp) in zip(cuts, want.v1_rec_in) {
                XCTAssertEqual(got, exp, accuracy: 0.0011, name)               // Python rounds halves to even, Swift away from zero
            }
            XCTAssertEqual(tl.items.filter { $0.kind == "text" }.sorted { $0.recIn < $1.recIn }.compactMap(\.text), want.texts, name)
            XCTAssertEqual(Set(tl.suggestions.map { $0.key ?? "" }), Set(want.suggestion_keys), name)
        }
    }

    func testDesktopPlansReadTheSame() throws {
        let day = try PreProJSON.decoder().decode(StoryPlan.self, from: golden("day_in_life", "story.json"))
        XCTAssertEqual(day.items.first?.role, "hook")
        XCTAssertTrue(day.items.allSatisfy { $0.beats != nil })                 // a beat-cut format
        XCTAssertEqual(day.sections.first?.name, "morning")
        let polish = try PreProJSON.decoder().decode(PolishPlan.self, from: golden("day_in_life", "polish.json"))
        XCTAssertEqual(polish.effects.filter { $0.intent == "stamp" }.first?.text, "6:42 am")
        XCTAssertNotNil(polish.music.first?.offset)                             // the song starts where the beat grid does
        let words = try PreProJSON.decoder().decode(PolishPlan.self, from: golden("text_reel", "polish.json"))
        XCTAssertEqual(words.effects.filter { $0.type == "text" }.map(\.at), ["clip:0", "clip:1", "clip:2", "clip:3"])
    }

    func testATimelineWritesBackUnchanged() throws {
        for name in ["photo_reel", "day_in_life", "text_reel"] {
            let tl = try PreProJSON.decoder().decode(Timeline.self, from: golden(name, "timeline.json"))
            let again = try PreProJSON.decoder().decode(Timeline.self, from: PreProJSON.encoder().encode(tl))
            XCTAssertEqual(tl, again, name)
        }
    }
}
