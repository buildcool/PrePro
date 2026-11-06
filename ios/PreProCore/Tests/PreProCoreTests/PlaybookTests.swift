import XCTest
@testable import PreProCore

/// The playbooks come straight from the desktop's knowledge/playbooks.yaml: every genre is there, with the same
/// numbers, and YAML's traps don't bite (a quoted "off" stays a string).
final class PlaybookTests: XCTestCase {
    func testEveryGenreIsThere() throws {
        let all = try Knowledge.playbooks()
        for key in ["story_vlog", "travel_film", "hype_reel", "aesthetic", "day_in_life", "text_reel", "teaser", "talking_head",
                    "podcast_clip", "gaming", "comedy", "photo_reel"] {
            XCTAssertNotNil(all[key], key)
            XCTAssertEqual(all[key]?.key, key)
        }
    }

    func testTheNumbersMatchTheDesktop() throws {
        let day = try Knowledge.playbook("day_in_life")
        XCTAssertEqual(day.name, "Day in my life")
        XCTAssertEqual(day.aspect, "9:16")
        XCTAssertEqual(day.target, [15, 60])
        XCTAssertEqual(day.pacing.brollShot, [1.0, 2.4])
        XCTAssertEqual(day.budget("text"), 24)
        XCTAssertEqual(day.budget("meme"), 0)
        XCTAssertEqual(day.music["bpm"], .array([.number(80), .number(125)]))
        XCTAssertEqual(day.music["avoid"], .array([.string("hype"), .string("epic")]))
        XCTAssertTrue(day.signature.contains("time_stamps"))

        let words = try Knowledge.playbook("text_reel")
        XCTAssertEqual(words.captions["default"], .string("off"))           // quoted "off": a string, not false
        XCTAssertEqual(try Knowledge.playbook("photo_reel").captions["default"], .string("off"))
        XCTAssertEqual(try Knowledge.playbook("story_vlog").splitEdits["j"], 0.5)
    }

    func testAnUnknownPlaybookSaysSo() {
        XCTAssertThrowsError(try Knowledge.playbook("not_a_genre"))
    }
}
