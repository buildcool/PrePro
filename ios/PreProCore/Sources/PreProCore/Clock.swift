import Foundation

/// When a clip was shot, on the creator's own clock — a port of the desktop's src/prepro/analyze/clock.py.
///
/// "6:42 am" on a day-in-my-life cut has to be the time the creator lived, not a file's UTC stamp:
/// an iPhone video carries its local creation date with the offset; a photo carries its EXIF time (with
/// OffsetTimeOriginal when the camera wrote one); most Android videos carry only UTC, which goes into the shoot's zone
/// (the one the shoot's other files state, else this phone's). A shooting day runs 4 am to 4 am.
public struct LocalTime: Equatable, Hashable, Sendable {
    public let date: Date
    public let zone: TimeZone

    public init(date: Date, zone: TimeZone) {
        self.date = date
        self.zone = zone
    }

    var calendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = zone
        return c
    }

    public var hour: Int { calendar.component(.hour, from: date) }
    public var minute: Int { calendar.component(.minute, from: date) }

    public func adding(seconds: Double) -> LocalTime { LocalTime(date: date.addingTimeInterval(seconds), zone: zone) }
}

/// A clip's time stamps as its file states them (from AVAsset / EXIF metadata, or the desktop's MediaInfo).
public struct ClipTimes: Equatable, Sendable {
    public var creationTime: String?               // ISO 8601, e.g. "2026-10-17T01:12:00Z" or with an offset
    public var tags: [String: String]              // e.g. com.apple.quicktime.creationdate
    public var isImage: Bool

    public init(creationTime: String? = nil, tags: [String: String] = [:], isImage: Bool = false) {
        self.creationTime = creationTime
        self.tags = tags
        self.isImage = isImage
    }
}

public enum Clock {
    public static let appleCreationDate = "com.apple.quicktime.creationdate"
    public static let dayStartsAt = 4                                   // hours after midnight

    static let parts: [(until: Double, name: String)] = [
        (4, "night"), (11.5, "morning"), (14, "midday"), (17.5, "afternoon"), (21, "evening"), (24.01, "night"),
    ]

    /// Parses ISO 8601 as PrePro's files write it: "2026-10-17T06:42:00+0530", "…+05:30", "…Z", fractions allowed, or
    /// no zone at all (then it is a wall clock, read in `naiveZone`). The second value says whether a zone was written.
    public static func parse(_ text: String?, naiveZone: TimeZone = .current) -> (time: LocalTime, hasZone: Bool)? {
        guard let s = text?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
        let pattern = #"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:?\d{2})?$"#
        guard let re = try? NSRegularExpression(pattern: pattern),
              let m = re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) else { return nil }
        func group(_ i: Int) -> String? {
            guard let r = Range(m.range(at: i), in: s) else { return nil }
            return String(s[r])
        }
        var zone = naiveZone
        var hasZone = false
        if let z = group(8) {
            hasZone = true
            if z == "Z" {
                zone = TimeZone(secondsFromGMT: 0)!
            } else {
                let sign = z.hasPrefix("-") ? -1 : 1
                let digits = z.dropFirst().replacingOccurrences(of: ":", with: "")
                let hh = Int(digits.prefix(2)) ?? 0, mm = Int(digits.suffix(2)) ?? 0
                guard let tz = TimeZone(secondsFromGMT: sign * (hh * 3600 + mm * 60)) else { return nil }
                zone = tz
            }
        }
        var comps = DateComponents()
        comps.year = Int(group(1) ?? "")
        comps.month = Int(group(2) ?? "")
        comps.day = Int(group(3) ?? "")
        comps.hour = Int(group(4) ?? "")
        comps.minute = Int(group(5) ?? "")
        comps.second = Int(group(6) ?? "0") ?? 0
        if let frac = group(7) { comps.nanosecond = Int((Double("0." + frac) ?? 0) * 1e9) }
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = zone
        guard let date = cal.date(from: comps) else { return nil }
        return (LocalTime(date: date, zone: zone), hasZone)
    }

    /// The clip's own local time, when its file states it with an offset; nil when it only has UTC or nothing.
    public static func ownLocal(_ clip: ClipTimes) -> LocalTime? { ownLocalStated(clip)?.time }

    /// The clip's own local time and whether the file wrote its offset (a photo's EXIF time may come without one).
    static func ownLocalStated(_ clip: ClipTimes) -> (time: LocalTime, hasZone: Bool)? {
        if let p = parse(clip.tags[appleCreationDate]), p.hasZone { return p }
        if clip.isImage, let p = parse(clip.creationTime) { return p }   // EXIF is the camera's own clock
        return nil
    }

    /// The shoot's UTC offset as its files state it (the most common one); nil when no file states one.
    public static func shootZone(_ clips: [ClipTimes]) -> TimeZone? {
        var counts: [Int: Int] = [:]
        for c in clips {
            if let p = ownLocalStated(c), p.hasZone { counts[p.time.zone.secondsFromGMT(for: p.time.date), default: 0] += 1 }
        }
        guard let best = counts.max(by: { ($0.value, -$0.key) < ($1.value, -$1.key) }) else { return nil }
        return TimeZone(secondsFromGMT: best.key)
    }

    /// When this was shot, on the creator's clock. `deviceZone` stands for "this phone's zone" (the desktop's
    /// "this computer's").
    public static func localTime(_ clip: ClipTimes, zone: TimeZone? = nil, deviceZone: TimeZone = .current) -> LocalTime? {
        if let own = ownLocal(clip) { return own }
        guard let p = parse(clip.creationTime, naiveZone: deviceZone) else { return nil }
        if !p.hasZone { return p.time }                  // written without a zone: already the camera's local time
        return LocalTime(date: p.time.date, zone: zone ?? deviceZone)
    }

    /// The shooting day, "yyyy-MM-dd": the 1 am ride home belongs to the night before.
    public static func shootingDay(_ t: LocalTime) -> String {
        let shifted = t.date.addingTimeInterval(-Double(dayStartsAt) * 3600)
        let c = t.calendar.dateComponents([.year, .month, .day], from: shifted)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    public static func partOfDay(_ t: LocalTime) -> String {
        let h = Double(t.hour) + Double(t.minute) / 60
        return parts.first { h < $0.until }?.name ?? "night"
    }

    /// "6:42 am" — the small time stamp on a day-in-my-life moment.
    public static func stamp(_ t: LocalTime) -> String {
        let h = t.hour % 12 == 0 ? 12 : t.hour % 12
        return String(format: "%d:%02d %@", h, t.minute, t.hour < 12 ? "am" : "pm")
    }

    /// Cameras with a dead clock write 1970/1904/2000-01-01 or future dates: those count as unknown.
    public static func plausible(_ t: LocalTime?, now: Date = Date()) -> LocalTime? {
        guard let t else { return nil }
        let ts = t.date.timeIntervalSince1970
        return (946_771_200 ... now.timeIntervalSince1970 + 2 * 86_400).contains(ts) ? t : nil
    }
}
