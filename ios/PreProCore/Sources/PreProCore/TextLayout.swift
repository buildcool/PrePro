import Foundation

/// How big words are on screen and where their lines break — the desktop's timeline/captions.py (`text_block`,
/// `balance_lines`, `STYLES`, `SAFE`), measured with the same fonts' advance widths (Resources/text_metrics.json, written
/// by scripts/export_parity.py from the bundled fonts), so both apps break your lines in the same places and find the
/// same room beside a face.
public enum TextLayout {
    public struct Style: Decodable, Equatable, Sendable {
        public let font: String
        public let size: Double                // as a fraction of the frame height
        public let primary: String
        public let outline: String
        public let bold: Int
        public let upper: Bool
    }

    struct FontFile: Decodable {
        let file: String
        let line_h: Double
        let notdef: Double
        let advances: [String: Double]
    }

    struct MetricsFile: Decodable {
        let safe: [String: [Double]]
        let glue: [String]
        let libass_width: [String: Double]
        let fonts: [String: FontFile]
        let styles: [String: Style]
    }

    /// A font's advance widths at size 100 (Pillow, basic layout): a text's width is the plain sum.
    struct Font {
        let lineH: Double
        let notdef: Double
        let advances: [UInt32: Double]

        func width(_ s: String) -> Double {
            var w = 0.0
            for u in s.unicodeScalars { w += advances[u.value] ?? notdef }
            return w
        }
    }

    struct Metrics {
        let safe: [String: [Double]]
        let glue: Set<String>
        let libassWidth: [String: Double]
        let fonts: [String: Font]
        let styles: [String: Style]
    }

    static let metrics: Metrics = {
        guard let url = Bundle.module.url(forResource: "text_metrics", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let m = try? JSONDecoder().decode(MetricsFile.self, from: data) else {
            preconditionFailure("text_metrics.json is not in PreProCore's bundle")
        }
        var fonts: [String: Font] = [:]
        for (name, f) in m.fonts {
            var adv: [UInt32: Double] = [:]
            for (cp, w) in f.advances {
                if let v = UInt32(cp) { adv[v] = w }
            }
            fonts[name] = Font(lineH: f.line_h, notdef: f.notdef, advances: adv)
        }
        return Metrics(safe: m.safe, glue: Set(m.glue), libassWidth: m.libass_width, fonts: fonts, styles: m.styles)
    }()

    /// The platform's UI overlays as (top, bottom, side) fractions of the frame: words stay inside.
    public static func safe(vertical: Bool) -> (top: Double, bottom: Double, side: Double) {
        let s = metrics.safe[vertical ? "9:16" : "16:9"] ?? [0.06, 0.08, 0.05]
        return (s[0], s[1], s[2])
    }

    public static func style(_ name: String) -> Style? { metrics.styles[name] ?? metrics.styles["clean"] }

    /// (lines, block height as a fraction of the frame height) for words in `style` at `scale` × its size.
    public static func textBlock(_ text: String, style name: String, width W: Int, height H: Int, scale: Double = 1.0) -> (lines: [String], height: Double) {
        guard let st = style(name) else { return ([text], 0) }
        let vertical = H > W
        let fs = Double(H) * st.size * (vertical ? 1.0 : 0.9) * scale
        let cap = Double(W) * (1 - 2 * safe(vertical: vertical).side)
        let measure: (String) -> Double
        if let font = metrics.fonts[st.font] {
            let k = fs / font.lineH * (metrics.libassWidth[st.font] ?? 0.9) * 1.03    // what libass draws, +3 % to be safe
            measure = { font.width($0) * k }
        } else {
            measure = { Double($0.unicodeScalars.count) * fs * 0.42 }
        }
        let lines = balanceLines(text, cap: cap, measure: measure)
        return (lines, Double(lines.count) * fs * 1.22 / Double(H))
    }

    /// The word as the glue check sees it: letters, digits, _ and ' only, lower case.
    static func bare(_ word: String) -> String {
        var out = String.UnicodeScalarView()
        for u in word.lowercased().unicodeScalars {
            switch u.properties.generalCategory {
            case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter, .decimalNumber, .letterNumber, .otherNumber:
                out.append(u)
            default:
                if u == "_" || u == "'" { out.append(u) }
            }
        }
        return String(out)
    }

    /// Words in as few lines as fit `cap` (in `measure` units), of similar length, never ending a line on a glue word
    /// ("the", "a", "to" …): "POV: you finally took / the trip you kept postponing", not "…took the / trip…".
    public static func balanceLines(_ text: String, cap: Double, measure: (String) -> Double) -> [String] {
        let words = Py.words(text).map(String.init)
        let total = measure(text)
        if total <= cap || words.count < 2 { return [text] }
        let count = words.count
        var found: [(score: Double, lines: [String])] = []
        let first = max(2, Int((total / cap).rounded(.up)))
        guard first <= count else { return words }
        for n in first...count {                       // fewest lines that fit — or one more, when that keeps a "the" off a line end
            if found.count == 2 || (found.first.map { $0.score < 0.1 } ?? false) { break }
            let target = total / Double(n)
            func cost(_ i: Int, _ j: Int) -> Double {
                let w = measure(words[i..<j].joined(separator: " "))
                let d = (w - target) / cap
                var c = d * d + (w > cap && j - i > 1 ? 1e6 : 0.0)
                if j < count && metrics.glue.contains(bare(words[j - 1])) { c += 0.15 }
                return c
            }
            var memo: [Int: (score: Double, cuts: [Int])] = [:]
            func best(_ i: Int, _ k: Int) -> (score: Double, cuts: [Int]) {
                let key = i * 4096 + k
                if let m = memo[key] { return m }
                var out: (score: Double, cuts: [Int]) = (.infinity, [count])
                if k == 1 {
                    out = (cost(i, count), [count])
                } else if i + 1 <= count - k + 1 {
                    var first = true
                    for j in (i + 1)...(count - k + 1) {
                        let rest = best(j, k - 1)
                        let cand = (score: cost(i, j) + rest.score, cuts: [j] + rest.cuts)
                        if first || cand.score < out.score || (cand.score == out.score && cand.cuts.lexicographicallyPrecedes(out.cuts)) {
                            out = cand
                            first = false
                        }
                    }
                }
                memo[key] = out
                return out
            }
            let (score, cuts) = best(0, n)
            if score < 1e6 || n == count {
                var lines: [String] = []
                var i = 0
                for j in cuts {
                    lines.append(words[i..<j].joined(separator: " "))
                    i = j
                }
                found.append((score + 0.1 * Double(found.count), lines))
            }
        }
        guard var pick = found.first else { return words }
        for f in found.dropFirst() where f.score < pick.score { pick = f }
        return pick.lines
    }
}
