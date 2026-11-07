import XCTest
@testable import PreProCore

/// The phone's rules engine reaches the desktop's decisions on the same shoots (scripts/export_parity.py writes what
/// the desktop decided): the music it picks and why, the beat grid, and a photo reel's story and polish — every
/// photo, every beat, every word on screen and every reason.
final class BrainParityTests: XCTestCase {
    let cases = ["photo_reel", "photo_single", "day_in_life", "text_reel"]

    func golden<T: Decodable>(_ type: T.Type, _ name: String, _ file: String) throws -> T {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil), "Golden folder not bundled")
        let data = try Data(contentsOf: dir.appendingPathComponent(name).appendingPathComponent(file))
        do {
            return try PreProJSON.decoder().decode(T.self, from: data)
        } catch {
            XCTFail("\(name)/\(file): \(error)")
            throw error
        }
    }

    struct MusicGolden: Decodable {
        struct Ranked: Decodable {
            let asset_id: String
            let score: Double
            let why: String
        }

        struct Job: Decodable {
            let brief: MusicBrief
            let ranked: [Ranked]
        }

        struct Grid: Decodable {
            let need: Double
            let playbook: String
            let track: String?
            let offset: Double
            let beat: Double
            let beats: [Double]
            let label: String?
            let bpm: Double
            let room: Double?
        }

        let front: Job
        let bed: Job
        let light: Job
        let grid: Grid
    }

    func testTheDesktopsAnalysisAndBriefRead() throws {
        for name in cases {
            let pa = try golden(ProjectAnalysis.self, name, "analysis.json")
            XCTAssertFalse(pa.assets.isEmpty, name)
            XCTAssertEqual(Set(pa.clips.keys), Set(pa.assets.map(\.id)), name)
            let again = try PreProJSON.decoder().decode(ProjectAnalysis.self, from: PreProJSON.encoder().encode(pa))
            XCTAssertEqual(again, pa, "\(name): the analysis doesn't survive a round trip")
            let brief = try golden(CreatorBrief.self, name, "brief.json")
            XCTAssertEqual(try PreProJSON.decoder().decode(CreatorBrief.self, from: PreProJSON.encoder().encode(brief)), brief, name)
        }
        let photos = try golden(ProjectAnalysis.self, "photo_reel", "analysis.json")
        let i02 = try XCTUnwrap(photos.asset("I02"))
        XCTAssertEqual(i02.kind, "image")
        XCTAssertEqual(i02.info.rotation, 90)
        XCTAssertTrue(i02.info.isVertical, "a landscape-stored photo turned upright is tall")
        XCTAssertEqual(photos.clips["I02"]?.place, "Calangute")
        XCTAssertEqual(photos.clips["A01"]?.music?.downbeats.count, 13)
    }

    func testMusicIsChosenTheSameWay() throws {
        for name in cases {
            let pa = try golden(ProjectAnalysis.self, name, "analysis.json")
            let brief = try golden(CreatorBrief.self, name, "brief.json")
            let d = try golden(Direction.self, name, "direction.json")
            let want = try golden(MusicGolden.self, name, "music.json")
            let pb = try Knowledge.playbook(d.playbook)
            for (mode, job) in [("front", want.front), ("bed", want.bed), ("light", want.light)] {
                let mb = Music.brief(for: mode, playbook: pb, mood: brief.prefs.musicMood, needSecs: want.grid.need, pace: d.knobs.pace)
                XCTAssertEqual(mb, job.brief, "\(name) \(mode): music brief")
                let ranked = Music.rankTracks(pa, brief: mb, mode: mode, avoid: Py.strings(pb.music["avoid"]))
                XCTAssertEqual(ranked.map(\.assetId), job.ranked.map(\.asset_id), "\(name) \(mode): track order")
                for (got, exp) in zip(ranked, job.ranked) {
                    XCTAssertEqual(got.score, exp.score, accuracy: 1e-9, "\(name) \(mode) \(got.assetId): score")
                    XCTAssertEqual(got.why, exp.why, "\(name) \(mode) \(got.assetId): reason")
                }
            }
            let grid = try RulesBrain(pa, brief: brief).reelGrid(need: want.grid.need, playbook: want.grid.playbook)
            XCTAssertEqual(grid.track, want.grid.track, "\(name): grid track")
            XCTAssertEqual(grid.offset, want.grid.offset, accuracy: 1e-9, "\(name): where the song starts")
            XCTAssertEqual(grid.beat, want.grid.beat, accuracy: 1e-9, "\(name): beat period")
            XCTAssertEqual(grid.label, want.grid.label, "\(name): part of the song")
            XCTAssertEqual(grid.bpm, want.grid.bpm, accuracy: 1e-9, "\(name): tempo")
            XCTAssertEqual(grid.room ?? -1, want.grid.room ?? -1, accuracy: 1e-9, "\(name): song left after the start")
            XCTAssertEqual(grid.beats.count, want.grid.beats.count, "\(name): beats on the grid")
            for (i, (got, exp)) in zip(grid.beats, want.grid.beats).enumerated() {
                XCTAssertEqual(got, exp, accuracy: 1e-9, "\(name): beat \(i)")
            }
        }
    }

    func testPhotoReelsAreCutTheSame() throws {
        for name in ["photo_reel", "photo_single"] {
            let pa = try golden(ProjectAnalysis.self, name, "analysis.json")
            let brief = try golden(CreatorBrief.self, name, "brief.json")
            let d = try golden(Direction.self, name, "direction.json")
            let want = try golden(StoryPlan.self, name, "brain_story.json")
            let wantPolish = try golden(PolishPlan.self, name, "brain_polish.json")
            let brain = RulesBrain(pa, brief: brief)
            let story = try brain.story(d)
            XCTAssertEqual(story.items.count, want.items.count, "\(name): photos in the reel")
            for (i, (got, exp)) in zip(story.items, want.items).enumerated() {
                XCTAssertEqual(got.ref, exp.ref, "\(name) item \(i): photo")
                XCTAssertEqual(got.role, exp.role, "\(name) item \(i): role")
                XCTAssertEqual(got.beats, exp.beats, "\(name) item \(i): beats")
                XCTAssertEqual(got.t1 ?? -1, exp.t1 ?? -1, accuracy: 1e-9, "\(name) item \(i): length")
                XCTAssertEqual(got.note, exp.note, "\(name) item \(i): note")
            }
            XCTAssertEqual(story.why, want.why, "\(name): story reason")
            XCTAssertEqual(story, want, "\(name): story")
            let polish = try brain.polish(d, story: story)
            XCTAssertEqual(polish.music, wantPolish.music, "\(name): music")
            XCTAssertEqual(polish.effects.count, wantPolish.effects.count, "\(name): words on screen")
            for (i, (got, exp)) in zip(polish.effects, wantPolish.effects).enumerated() {
                XCTAssertEqual(got, exp, "\(name) effect \(i)")
            }
            XCTAssertEqual(polish, wantPolish, "\(name): polish")
        }
    }

    func testPhotoReelRulesTheCreatorSet() throws {
        let pa = try golden(ProjectAnalysis.self, "photo_reel", "analysis.json")
        let d = try golden(Direction.self, "photo_reel", "direction.json")
        func rule(_ kind: String, _ target: String) -> HardRule {
            HardRule(kind: kind, target: target, anchor: "", value: nil, arg: [:], source: target, resolved: true)
        }
        var brief = CreatorBrief.empty
        brief.rules = [rule("no_effect", "loop"), rule("no_effect", "text"), rule("must_exclude", "I09")]
        let brain = RulesBrain(pa, brief: brief)
        let story = try brain.story(d)
        XCTAssertFalse(story.items.contains { $0.role == "loop" }, "no loop when you say so")
        XCTAssertFalse(story.items.contains { $0.ref.hasPrefix("I09") }, "a photo you left out stays out")
        XCTAssertTrue(try brain.polish(d, story: story).effects.isEmpty, "no words when you say no text")
        let order = brain.photos().map { $0.assetId }
        XCTAssertEqual(order, order.stableSorted { RulesBrain.instant(pa.asset($0)?.info.creationTime) < RulesBrain.instant(pa.asset($1)?.info.creationTime) },
                       "photos in the order they were taken")
    }

    func testPythonRounding() {
        // values where rounding the scaled number (x * 1000).rounded() gives the other answer
        XCTAssertEqual(Py.round(1.0005, 3), 1.0)           // stored a hair below the half: Python gives 1.0, not 1.001
        XCTAssertEqual(Py.round(1.2345, 3), 1.234)
        XCTAssertEqual(Py.round(0.0625, 3), 0.062)         // an exact half: to even
        XCTAssertEqual(Py.round(0.0125, 3), 0.013)         // stored a hair above the half
        XCTAssertEqual(Py.fixed(92.5, 0), "92")
        XCTAssertEqual(Py.fixed(14.443, 1), "14.4")
        XCTAssertEqual(Py.median([3, 1, 2, 10]), 2.5)
        XCTAssertEqual([3, 1, 2, 1].stableSorted { $0 > $1 }, [3, 2, 1, 1])
    }
}
