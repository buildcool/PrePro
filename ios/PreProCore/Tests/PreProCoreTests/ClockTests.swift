import XCTest
@testable import PreProCore

/// The same checks as the desktop's tests/unit/test_p8_day_clock.py: a clip's local time from what the phone wrote,
/// shooting days that run 4 am to 4 am, and "6:42 am" stamps.
final class ClockTests: XCTestCase {
    let ist = TimeZone(secondsFromGMT: 19_800)!                 // +05:30
    let utc = TimeZone(secondsFromGMT: 0)!

    func testALocalTimeIsWhatThePhoneShowed() throws {
        let iphone = ClipTimes(creationTime: "2026-10-17T01:12:00Z", tags: [Clock.appleCreationDate: "2026-10-17T06:42:00+0530"])
        let own = try XCTUnwrap(Clock.localTime(iphone, deviceZone: utc))
        XCTAssertEqual(own.zone.secondsFromGMT(), 19_800)          // its own local stamp wins
        XCTAssertEqual(Clock.stamp(own), "6:42 am")

        let android = ClipTimes(creationTime: "2026-10-17T01:12:00Z")
        XCTAssertEqual(Clock.stamp(try XCTUnwrap(Clock.localTime(android, zone: ist, deviceZone: utc))), "6:42 am")   // UTC, in the shoot's zone
        XCTAssertEqual(Clock.stamp(try XCTUnwrap(Clock.localTime(android, deviceZone: ist))), "6:42 am")            // or this phone's

        let photo = ClipTimes(creationTime: "2026-10-17T06:42:00+05:30", isImage: true)
        XCTAssertEqual(Clock.stamp(try XCTUnwrap(Clock.localTime(photo, zone: utc))), "6:42 am")   // EXIF is the camera's clock

        XCTAssertEqual(Clock.shootZone([android, iphone, photo])?.secondsFromGMT(), 19_800)       // what the files state
        XCTAssertNil(Clock.shootZone([android]))
        XCTAssertNil(Clock.localTime(ClipTimes()))
    }

    func testAClipWithOnlyItsLocalTimeStillCounts() throws {
        // what ffmpeg 9 writes: an iPhone-style local creation date and no UTC creation_time at all
        let clip = ClipTimes(tags: [Clock.appleCreationDate: "2026-10-17T23:05:00+0530"])
        XCTAssertEqual(Clock.stamp(try XCTUnwrap(Clock.localTime(clip))), "11:05 pm")
    }

    func testDaysRunFourToFourAndStampsReadLikeAPhone() throws {
        let late = try XCTUnwrap(Clock.parse("2026-10-18T01:30:00+05:30")).time
        XCTAssertEqual(Clock.shootingDay(late), "2026-10-17")                                   // the ride home is the night before
        XCTAssertEqual(Clock.shootingDay(try XCTUnwrap(Clock.parse("2026-10-18T04:10:00+05:30")).time), "2026-10-18")

        let stamps = [("06:42", "6:42 am"), ("00:05", "12:05 am"), ("12:00", "12:00 pm"), ("18:42", "6:42 pm"), ("23:05", "11:05 pm")]
        for (hhmm, want) in stamps {
            XCTAssertEqual(Clock.stamp(try XCTUnwrap(Clock.parse("2026-10-17T\(hhmm):00+05:30")).time), want)
        }
        let parts = [("07", "morning"), ("12", "midday"), ("15", "afternoon"), ("19", "evening"), ("22", "night"), ("02", "night")]
        for (hh, want) in parts {
            XCTAssertEqual(Clock.partOfDay(try XCTUnwrap(Clock.parse("2026-10-17T\(hh):00:00+05:30")).time), want)
        }
        XCTAssertNil(Clock.plausible(Clock.parse("1970-01-01T00:00:00Z")?.time))                 // a dead camera clock
        XCTAssertNotNil(Clock.plausible(late))
    }

    func testParsesWhatPhonesAndTheDesktopWrite() throws {
        for s in ["2026-10-17T06:42:00+0530", "2026-10-17T06:42:00+05:30", "2026-10-17T06:42:00.000+0530", "2026-10-17 06:42:00+05:30"] {
            let p = try XCTUnwrap(Clock.parse(s), s)
            XCTAssertTrue(p.hasZone, s)
            XCTAssertEqual(Clock.stamp(p.time), "6:42 am", s)
        }
        let naive = try XCTUnwrap(Clock.parse("2026-10-17T06:42:00", naiveZone: ist))
        XCTAssertFalse(naive.hasZone)
        XCTAssertEqual(Clock.stamp(naive.time), "6:42 am")
        XCTAssertNil(Clock.parse("yesterday"))
    }
}
