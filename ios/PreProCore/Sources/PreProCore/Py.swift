import Foundation

/// Python's behaviour in the few places where Swift's differs, so the phone reaches exactly the desktop's decisions:
/// rounding, number formatting, word splitting, string order, numpy's median and stable sorting.
enum Py {
    /// round(x, n): the decimal nearest the exact binary value, halves to even, which is what printf does too
    /// (Swift's rounded() goes away from zero on the scaled value, which differs in the last digit now and then).
    static func round(_ x: Double, _ digits: Int = 3) -> Double {
        guard x.isFinite else { return x }
        return Double(String(format: "%.\(digits)f", x)) ?? x
    }

    /// f"{x:.nf}"
    static func fixed(_ x: Double, _ digits: Int) -> String { String(format: "%.\(digits)f", x) }

    /// str.split(): the words between runs of whitespace.
    static func words(_ s: String) -> [Substring] { s.split(whereSeparator: \.isWhitespace) }

    /// str < str: code point order.
    static func less(_ a: String, _ b: String) -> Bool { a.unicodeScalars.lexicographicallyPrecedes(b.unicodeScalars) }

    /// numpy.diff
    static func diff(_ xs: [Double]) -> [Double] { zip(xs.dropFirst(), xs).map { $0 - $1 } }

    /// numpy.median
    static func median(_ xs: [Double]) -> Double {
        let s = xs.sorted()
        guard !s.isEmpty else { return .nan }
        let n = s.count
        return n % 2 == 1 ? s[n / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
    }

    /// numpy.arange(start, stop, step) for floats: ceil((stop - start) / step) values, start + i * delta where delta is
    /// (start + step) - start — numpy's own fill, so the last value lands where the desktop's does.
    static func arange(_ start: Double, _ stop: Double, _ step: Double) -> [Double] {
        let n = Int(((stop - start) / step).rounded(.up))
        guard n > 0 else { return [] }
        let second = start + step
        let delta = second - start
        return (0..<n).map { $0 == 0 ? start : ($0 == 1 ? second : start + Double($0) * delta) }
    }

    /// s[:n] — the first n characters as Python counts them (code points, not grapheme clusters).
    static func prefix(_ s: String, _ n: Int) -> String {
        var out = String.UnicodeScalarView()
        out.append(contentsOf: s.unicodeScalars.prefix(n))
        return String(out)
    }

    /// numpy.mean (numpy sums pairwise, which can differ only in the last bits)
    static func mean(_ xs: [Double]) -> Double { xs.isEmpty ? .nan : xs.reduce(0, +) / Double(xs.count) }

    /// Python's `x or None` for text: an empty string counts as nothing.
    static func text(_ s: String?) -> String? { (s?.isEmpty ?? true) ? nil : s }

    /// Python's `x or None` for a number: zero counts as nothing.
    static func number(_ x: Double?) -> Double? { (x ?? 0) == 0 ? nil : x }

    /// A list of words from a knowledge file (a playbook's music.prefer, music.avoid …).
    static func strings(_ v: JSONValue?) -> [String] { (v?.array ?? []).compactMap(\.string) }
}

extension Array {
    /// sorted(key=…) the Python way: equal elements keep their order.
    func stableSorted(by less: (Element, Element) -> Bool) -> [Element] {
        enumerated().sorted { a, b in
            if less(a.element, b.element) { return true }
            if less(b.element, a.element) { return false }
            return a.offset < b.offset
        }.map { $0.element }
    }
}
