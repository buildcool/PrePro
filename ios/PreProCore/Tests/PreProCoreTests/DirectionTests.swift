import XCTest
@testable import PreProCore

/// From a shoot of photos the phone proposes the desktop's cut: a photo reel of the same length, the same cover (and
/// the same two other covers), the same name, reason and outline.
final class DirectionTests: XCTestCase {
    func testPhotoShootsGetTheDesktopsDirection() throws {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil))
        for name in ["photo_reel", "photo_single"] {
            func load<T: Decodable>(_ t: T.Type, _ f: String) throws -> T {
                try JSONDecoder().decode(T.self, from: Data(contentsOf: dir.appendingPathComponent(name).appendingPathComponent(f)))
            }
            let pa = try load(ProjectAnalysis.self, "analysis.json")
            let want = try load(Direction.self, "direction.json")
            let ds = try RulesBrain(pa, brief: try load(CreatorBrief.self, "brief.json")).directions()
            let d = try XCTUnwrap(ds.first, name)
            XCTAssertEqual(d.knobs.targetLength, want.knobs.targetLength, "\(name): length")
            XCTAssertEqual(d.hooks, want.hooks, "\(name): the covers")
            XCTAssertEqual(d.name, want.name, name)
            XCTAssertEqual(d, want, name)
        }
    }

    func testTheTestDaysDirectionIsTheDesktops() throws {
        let (g, pa) = try PhotoShootTests.shoot()
        let d = try XCTUnwrap(try RulesBrain(pa, brief: g.brief).directions().first)
        XCTAssertEqual(d.hooks.map(\.refs), g.direction.hooks.map(\.refs), "the cover, then two other covers")
        XCTAssertEqual(d, g.direction)
    }

    func testVideoIsNotGuessed() throws {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil))
        let pa = try JSONDecoder().decode(ProjectAnalysis.self, from: Data(contentsOf: dir.appendingPathComponent("day_in_life/analysis.json")))
        XCTAssertThrowsError(try RulesBrain(pa).directions(), "a day of video clips isn't cut on the phone yet")
    }
}
