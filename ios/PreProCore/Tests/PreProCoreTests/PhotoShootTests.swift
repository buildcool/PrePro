import XCTest
@testable import PreProCore

/// A day of photos analysed on the phone is the desktop's analysis, and the reel cut from it is the desktop's reel
/// (Golden/photos/shoot.json): every photo measured, the burst copy, the out-of-focus and the dark photo found, the
/// burst split nowhere (one minute apart), the day and the town named, then the same story, polish and timeline.
final class PhotoShootTests: XCTestCase {
    struct Golden: Decodable {
        struct Photo: Decodable {
            let name: String
            let picture: PictureSynth.Spec
            let orientation: Int
            let creation_time: String
            let location: GeoPoint
            let faces: [[Double]]
        }

        let photos: [Photo]
        let analysis: ProjectAnalysis
        let brief: CreatorBrief
        let direction: Direction
        let story: StoryPlan
        let polish: PolishPlan
        let timeline: Timeline
    }

    nonisolated(unsafe) static var made: (Golden, ProjectAnalysis)?

    static func shoot() throws -> (Golden, ProjectAnalysis) {
        if let m = made { return m }
        let g = try PhotoAnalysisTests.golden(Golden.self, "shoot.json")
        let inputs = g.photos.map { p -> PhotoInput in
            let pic = PhotoAnalysisTests.picture(p.picture)
            let stored = Pillow.upright(pic, orientation: PhotoAnalysisTests.storing[p.orientation]!)
            let thumb = Pillow.thumbnail(Pillow.upright(stored, orientation: p.orientation))
            return PhotoInput(name: p.name, size: 0, formatName: "image2", width: stored.width, height: stored.height,
                              orientation: p.orientation, creationTime: p.creation_time, location: p.location, hash: "", thumbnail: thumb,
                              faces: PhotoAnalysisTests.boxes(p.faces))
        }
        let song = try XCTUnwrap(g.analysis.assets.first(where: { $0.kind == "music" }))
        let songClip = try XCTUnwrap(g.analysis.clips[song.id])
        let pa = PhotoShoot.analysis(photos: inputs.reversed(), music: (song, songClip),
                                     deviceZone: TimeZone(identifier: "Asia/Kolkata")!, now: Date(timeIntervalSince1970: 1_800_000_000))
        made = (g, pa)
        return (g, pa)
    }

    func testTheShootIsAnalysedAsTheDesktopDoes() throws {
        let (g, pa) = try Self.shoot()
        let want = g.analysis
        XCTAssertEqual(pa.assets.map(\.id), want.assets.map(\.id), "ids: the song, then the photos in name order")
        XCTAssertEqual(pa.assets, want.assets, "assets")
        for a in want.assets {
            let got = try XCTUnwrap(pa.clips[a.id], a.id), exp = try XCTUnwrap(want.clips[a.id], a.id)
            XCTAssertEqual(got.shots, exp.shots, "\(a.id): the photo's measures, its burst group and rank")
            XCTAssertEqual(got.place, exp.place, "\(a.id): place")
            XCTAssertEqual(got.placeCluster, exp.placeCluster, a.id)
            XCTAssertEqual(got.dayIndex, exp.dayIndex, "\(a.id): day")
            XCTAssertEqual(got.orderKey, exp.orderKey, "\(a.id): order")
            XCTAssertEqual(got, exp, a.id)
        }
        var stats = pa.stats, wantStats = want.stats
        stats["analysis_seconds"] = nil
        wantStats["analysis_seconds"] = nil
        XCTAssertEqual(stats, wantStats, "stats")
        XCTAssertEqual(pa.genres, want.genres, "the genre guess")
        XCTAssertEqual(pa.version, want.version)
        // what an editor leaves out of this day: the burst copy, the blurry and the dark photo
        let shot = { (id: String) in pa.clips[id]!.shots[0] }
        XCTAssertEqual(shot("I03").dupRank, 1, "the second frame of the burst")
        XCTAssertEqual(shot("I02").dupRank, 0)
        XCTAssertEqual(shot("I02").dupGroup, shot("I03").dupGroup)
        XCTAssertTrue(shot("I06").flags.contains("blurry"))
        XCTAssertTrue(shot("I10").flags.contains("dark"))
        XCTAssertEqual(pa.clips["I01"]?.place, "Calangute", "named offline, like the desktop")
    }

    func testTheReelIsTheDesktopsReel() throws {
        let (g, pa) = try Self.shoot()
        let brain = RulesBrain(pa, brief: g.brief)
        let story = try brain.story(g.direction)
        XCTAssertEqual(story.items.map(\.ref), g.story.items.map(\.ref), "the photos and their order")
        XCTAssertEqual(story, g.story, "story")
        let refs = story.items.map(\.ref)
        XCTAssertFalse(refs.contains("I03.k0") || refs.contains("I06.k0") || refs.contains("I10.k0"),
                       "no burst copy, no blurry and no dark photo")
        XCTAssertEqual(Array(refs.dropFirst()), ["I01.k0", "I02.k0", "I04.k0", "I05.k0", "I11.k0", "I07.k0", "I08.k0", "I09.k0"],
                       "after the cover, the day in the order it was taken (lunch with friends, named last, at lunchtime)")
        let polish = try brain.polish(g.direction, story: story)
        XCTAssertEqual(polish, g.polish, "polish")
        let tl = try Compiler.compile(pa, direction: g.direction, story: story, polish: polish, brief: g.brief)
        let want = g.timeline
        XCTAssertEqual(tl.duration, want.duration, accuracy: 1e-9, "length")
        XCTAssertEqual(tl.items.map(\.id), want.items.map(\.id), "items")
        for (a, b) in zip(tl.items, want.items) {
            XCTAssertEqual(a.kind, b.kind, b.id)
            XCTAssertEqual(a.assetId, b.assetId, b.id)
            XCTAssertEqual(a.recIn, b.recIn, accuracy: 1e-9, b.id)
            XCTAssertEqual(a.recOut, b.recOut, accuracy: 1e-9, b.id)
            XCTAssertEqual(a.text, b.text, b.id)
        }
        XCTAssertEqual(tl.suggestions.map(\.id), want.suggestions.map(\.id), "decisions")
        XCTAssertEqual(tl.suggestions.map(\.reason), want.suggestions.map(\.reason), "every decision's reason")
    }
}
