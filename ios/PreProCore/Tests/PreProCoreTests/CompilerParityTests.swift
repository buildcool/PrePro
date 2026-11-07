import XCTest
@testable import PreProCore

/// The phone lays out a photo reel exactly as the desktop does (Golden/<case>/timeline.json): every photo on its beat,
/// its move, the words where the desktop puts them (off the faces, the same line breaks), the song with its level, and
/// every decision with its reason and the key the review keeps or rejects it by.
final class CompilerParityTests: XCTestCase {
    func golden<T: Decodable>(_ type: T.Type, _ name: String, _ file: String) throws -> T {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil), "Golden folder not bundled")
        let url = name.isEmpty ? dir.appendingPathComponent(file) : dir.appendingPathComponent(name).appendingPathComponent(file)
        do {
            return try PreProJSON.decoder().decode(T.self, from: Data(contentsOf: url))
        } catch {
            XCTFail("\(name)/\(file): \(error)")
            throw error
        }
    }

    struct TextBlock: Decodable {
        let text: String
        let style: String
        let width: Int
        let height: Int
        let scale: Double
        let lines: [String]
        let block: Double
    }

    func testLinesBreakWhereTheDesktopBreaksThem() throws {
        for c in try golden([TextBlock].self, "", "text_blocks.json") {
            let got = TextLayout.textBlock(c.text, style: c.style, width: c.width, height: c.height, scale: c.scale)
            XCTAssertEqual(got.lines, c.lines, "\(c.style) \(c.scale): \(c.text)")
            XCTAssertEqual(got.height, c.block, accuracy: 1e-12, "\(c.style) \(c.scale): \(c.text)")
        }
        XCTAssertEqual(TextLayout.safe(vertical: true).bottom, 0.24)
        XCTAssertEqual(TextLayout.style("photo")?.font, "Montserrat")
    }

    func close(_ a: Double?, _ b: Double?, _ what: String, file: StaticString = #filePath, line: UInt = #line) {
        switch (a, b) {
        case (nil, nil): return
        case let (x?, y?): XCTAssertEqual(x, y, accuracy: 1e-9, what, file: file, line: line)
        default: XCTFail("\(what): \(String(describing: a)) vs \(String(describing: b))", file: file, line: line)
        }
    }

    func compare(_ got: Item, _ exp: Item, _ at: String) {
        XCTAssertEqual(got.id, exp.id, "\(at) id")
        XCTAssertEqual(got.ref, exp.ref, "\(at) ref")
        XCTAssertEqual(got.track, exp.track, "\(at) track")
        XCTAssertEqual(got.kind, exp.kind, "\(at) kind")
        XCTAssertEqual(got.assetId, exp.assetId, "\(at) asset")
        close(got.srcIn, exp.srcIn, "\(at) src_in")
        close(got.srcOut, exp.srcOut, "\(at) src_out")
        close(got.recIn, exp.recIn, "\(at) rec_in")
        close(got.speed, exp.speed, "\(at) speed")
        XCTAssertEqual(got.link, exp.link, "\(at) link")
        XCTAssertEqual(got.transform == nil, exp.transform == nil, "\(at) has a move")
        if let g = got.transform, let e = exp.transform {
            close(g.cx, e.cx, "\(at) cx")
            close(g.cy, e.cy, "\(at) cy")
            close(g.zoom, e.zoom, "\(at) zoom")
            XCTAssertEqual(g.fit, e.fit, "\(at) fit")
            XCTAssertEqual(g.keys.count, e.keys.count, "\(at) keys")
            for (k, (gk, ek)) in zip(g.keys, e.keys).enumerated() {
                close(gk.t, ek.t, "\(at) key \(k) t")
                close(gk.cx, ek.cx, "\(at) key \(k) cx")
                close(gk.cy, ek.cy, "\(at) key \(k) cy")
                close(gk.zoom, ek.zoom, "\(at) key \(k) zoom")
            }
        }
        close(got.gainDb, exp.gainDb, "\(at) gain")
        XCTAssertEqual(got.envelope.count, exp.envelope.count, "\(at) envelope points")
        for (g, e) in zip(got.envelope, exp.envelope) {
            XCTAssertEqual(g.count, e.count, "\(at) envelope point")
            for (x, y) in zip(g, e) { close(x, y, "\(at) envelope") }
        }
        close(got.fadeIn, exp.fadeIn, "\(at) fade in")
        close(got.fadeOut, exp.fadeOut, "\(at) fade out")
        XCTAssertEqual(got.transitionIn, exp.transitionIn, "\(at) transition")
        XCTAssertEqual(got.text, exp.text, "\(at) text")
        XCTAssertEqual(got.style, exp.style, "\(at) style")
        XCTAssertEqual(got.position, exp.position, "\(at) position")
        close(got.textY, exp.textY, "\(at) text_y")
        close(got.textScale, exp.textScale, "\(at) text_scale")
        close(got.duration, exp.duration, "\(at) duration")
        XCTAssertEqual(got.role, exp.role, "\(at) role")
        XCTAssertEqual(got.section, exp.section, "\(at) section")
        XCTAssertEqual(got.note, exp.note, "\(at) note")
    }

    func testPhotoReelsAreLaidOutTheSame() throws {
        for name in ["photo_reel", "photo_single"] {
            let pa = try golden(ProjectAnalysis.self, name, "analysis.json")
            let brief = try golden(CreatorBrief.self, name, "brief.json")
            let d = try golden(Direction.self, name, "direction.json")
            let story = try golden(StoryPlan.self, name, "story.json")
            let polish = try golden(PolishPlan.self, name, "polish.json")
            let want = try golden(Timeline.self, name, "timeline.json")
            let tl = try Compiler.compile(pa, direction: d, story: story, polish: polish, brief: brief)
            XCTAssertEqual(tl.id, want.id, name)
            XCTAssertEqual(tl.name, want.name, name)
            XCTAssertEqual(tl.playbook, want.playbook, name)
            XCTAssertEqual(tl.width, want.width, name)
            XCTAssertEqual(tl.height, want.height, name)
            XCTAssertEqual(tl.look, want.look, name)
            XCTAssertEqual(tl.duration, want.duration, accuracy: 1e-9, "\(name): length")
            XCTAssertEqual(tl.items.map(\.id), want.items.map(\.id), "\(name): items, in order")
            for (got, exp) in zip(tl.items, want.items) { compare(got, exp, "\(name) \(exp.id)") }
            XCTAssertEqual(tl.suggestions.map(\.id), want.suggestions.map(\.id), "\(name): decisions")
            for (got, exp) in zip(tl.suggestions, want.suggestions) {
                let at = "\(name) \(exp.id) \(exp.type)"
                XCTAssertEqual(got.type, exp.type, at)
                XCTAssertEqual(got.status, exp.status, at)
                XCTAssertEqual(got.confidence, exp.confidence, accuracy: 1e-9, at)
                XCTAssertEqual(got.reason, exp.reason, at)
                XCTAssertEqual(got.source, exp.source, at)
                close(got.t, exp.t, "\(at) t")
                XCTAssertEqual(got.itemIds, exp.itemIds, at)
                XCTAssertEqual(JSONValue.object(got.payload).withoutNulls, JSONValue.object(exp.payload).withoutNulls, "\(at) payload")
                XCTAssertEqual(got.alternatives, exp.alternatives, at)
            }
            XCTAssertEqual(tl.markers.count, want.markers.count, "\(name): markers")
            for (got, exp) in zip(tl.markers, want.markers) {
                close(got.t, exp.t, "\(name) marker t")
                XCTAssertEqual(got.name, exp.name, "\(name) marker")
                XCTAssertEqual(got.note, exp.note, "\(name) marker note")
                XCTAssertEqual(got.color, exp.color, "\(name) marker colour")
                XCTAssertEqual(got.suggestionId, exp.suggestionId, "\(name) marker decision")
            }
            XCTAssertEqual(tl.musicSpans.count, want.musicSpans.count, "\(name): music spans")
            for (got, exp) in zip(tl.musicSpans, want.musicSpans) {
                close(got.t0, exp.t0, "\(name) span t0")
                close(got.t1, exp.t1, "\(name) span t1")
                XCTAssertEqual(got.mode, exp.mode, name)
                XCTAssertEqual(got.section, exp.section, name)
            }
            XCTAssertEqual(JSONValue.object(tl.meta).withoutNulls, JSONValue.object(want.meta).withoutNulls, "\(name): meta")
            XCTAssertTrue(tl.captions.isEmpty, name)
        }
    }

    func testTheWholeChainOnThePhone() throws {
        // analysis + brief → the brain → the compiler, all on the phone: the same timeline as the desktop's
        let pa = try golden(ProjectAnalysis.self, "photo_reel", "analysis.json")
        let brief = try golden(CreatorBrief.self, "photo_reel", "brief.json")
        let d = try golden(Direction.self, "photo_reel", "direction.json")
        let brain = RulesBrain(pa, brief: brief)
        let story = try brain.story(d)
        let tl = try Compiler.compile(pa, direction: d, story: story, polish: try brain.polish(d, story: story), brief: brief)
        let want = try golden(Timeline.self, "photo_reel", "timeline.json")
        XCTAssertEqual(tl.track("V1").map(\.assetId), want.track("V1").map(\.assetId))
        XCTAssertEqual(tl.duration, want.duration, accuracy: 1e-9)
        XCTAssertEqual(Set(tl.suggestions.compactMap(\.key)), Set(want.suggestions.compactMap(\.key)))
    }

    func testNoZoomsMeansStillPhotos() throws {
        let pa = try golden(ProjectAnalysis.self, "photo_reel", "analysis.json")
        let d = try golden(Direction.self, "photo_reel", "direction.json")
        let story = try golden(StoryPlan.self, "photo_reel", "story.json")
        let polish = try golden(PolishPlan.self, "photo_reel", "polish.json")
        var brief = CreatorBrief.empty
        brief.rules = [HardRule(kind: "no_effect", target: "zoom", anchor: "", value: nil, arg: [:], source: "no zooms", resolved: true)]
        let tl = try Compiler.compile(pa, direction: d, story: story, polish: polish, brief: brief)
        let photos = tl.track("V1").filter { $0.role != "loop" }
        XCTAssertFalse(photos.isEmpty)
        XCTAssertTrue(photos.allSatisfy { $0.transform?.keys.isEmpty ?? true }, "framed, still")
        XCTAssertFalse(tl.suggestions.contains { $0.key == "photomotion" }, "nothing moves, so no motion decision to review")
    }

    func testArangeIsNumpys() {
        XCTAssertEqual(Py.arange(0.0, 13.239, 0.05).count, 265)
        XCTAssertEqual(Py.arange(0.0, 13.1, 0.05).count, 262)
        XCTAssertEqual(Py.prefix("POV: you finally took the trip", 24), "POV: you finally took th")
    }
}
