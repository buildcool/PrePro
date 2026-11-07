import Foundation

/// The test songs the desktop's analysis is checked on (scripts/portable_song.py), made sample for sample on the phone:
/// drums, bass, chords and lead on an exactly known beat grid. The noise in the drums comes from SplitMix64 +
/// Box–Muller, the same numbers in both apps; the arithmetic follows numpy's (float32 buffers, double-precision maths).
public enum SongSynth {
    public struct Section: Sendable {
        public var label: String
        public var bars: Int
        public var energy: Double

        public init(_ label: String, _ bars: Int, _ energy: Double) {
            self.label = label
            self.bars = bars
            self.energy = energy
        }
    }

    public struct Truth: Sendable {
        public var beats: [Double]
        public var downbeats: [Double]
        public var sections: [(label: String, t0: Double, t1: Double, energy: Double)]
    }

    /// SplitMix64 → uniforms in (0, 1] → Box–Muller normals.
    struct Rng {
        var state: UInt64

        mutating func next() -> UInt64 {
            state &+= 0x9E37_79B9_7F4A_7C15
            var z = state
            z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
            z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
            return z ^ (z >> 31)
        }

        mutating func uniform() -> Double { Double((next() >> 11) + 1) * (1.0 / 9_007_199_254_740_992.0) }

        mutating func normals(_ n: Int) -> [Double] {
            var out = [Double]()
            out.reserveCapacity(n)
            for _ in 0..<n {
                let u1 = uniform()
                let u2 = uniform()
                out.append((-2.0 * log(u1)).squareRoot() * cos(2.0 * Double.pi * u2))
            }
            return out
        }
    }

    static let notes = ["C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11]

    static func midiHz(_ m: Double) -> Double { 440.0 * pow(2, (m - 69) / 12) }

    static func env(_ n: Int, _ a: Double, _ d: Double, _ sr: Double) -> [Float] {
        (0..<n).map { i in
            let t = Double(i) / sr
            return Float(min(1.0, t / max(a, 1e-4)) * exp(-t / max(d, 1e-4)))
        }
    }

    static func kick(_ sr: Double) -> [Float] {
        let n = Int(0.35 * sr)
        var ph = 0.0
        return (0..<n).map { i in
            let t = Double(i) / sr
            ph += 120 * exp(-t * 18) + 42                     // np.cumsum, in order
            return Float(sin(2 * Double.pi * ph / sr) * exp(-t * 9))
        }
    }

    static func snare(_ rng: inout Rng, _ sr: Double) -> [Float] {
        let n = Int(0.22 * sr)
        let noise = rng.normals(n)
        return (0..<n).map { i in
            let t = Double(i) / sr
            let tone = sin(2 * Double.pi * 190 * t) * exp(-t * 25)
            return Float(0.5 * tone + 0.6 * (noise[i] * exp(-t * 18)))
        }
    }

    static func hat(_ rng: inout Rng, _ sr: Double) -> [Float] {
        let n = Int(0.06 * sr)
        let noise = rng.normals(n)
        return (0..<n).map { i in
            let d = noise[i] - (i > 0 ? noise[i - 1] : 0)       // np.diff(prepend=0): a crude high-pass
            return Float(d * exp(-Double(i) / sr * 70) * 0.25)
        }
    }

    static func tone(_ freq: Double, _ dur: Double, _ kind: String, _ sr: Double) -> [Float] {
        let n = Int(dur * sr)
        return (0..<n).map { i in
            let t = Double(i) / sr
            switch kind {
            case "sine":
                return Float(sin(2 * Double.pi * freq * t))
            case "square":
                let s = sin(2 * Double.pi * freq * t)
                return Float((s > 0 ? 1.0 : (s < 0 ? -1.0 : 0.0)) * 0.6)
            default:                                           // a saw from six harmonics, summed like Python's sum()
                var y = 0.0
                for k in 1...6 { y += sin(2 * Double.pi * freq * Double(k) * t) / Double(k) }
                return Float(y)
            }
        }
    }

    static func add(_ buf: inout [Float], _ y: [Float], _ at: Int, _ gain: Double = 1.0) {
        guard at < buf.count else { return }
        let g = Float(gain)
        let end = min(buf.count, at + y.count)
        for i in at..<end { buf[i] += y[i - at] * g }
    }

    /// (samples, truth) for a song: the fixture synth at `sampleRate`.
    public static func song(bpm: Double = 100, sections: [Section]? = nil, key: String = "A", minor: Bool = true, seed: UInt64 = 0,
                            swing: Double = 0, vocalHum: Bool = false, sampleRate sr: Double = 22050) -> ([Float], Truth) {
        let secs = sections ?? [Section("intro", 4, 0.3), Section("build", 4, 0.6), Section("drop", 8, 1.0), Section("outro", 4, 0.35)]
        var rng = Rng(state: seed)
        let beat = 60.0 / bpm
        let totalBars = secs.reduce(0) { $0 + $1.bars }
        let dur = Double(totalBars * 4) * beat + 1.5
        var buf = [Float](repeating: 0, count: Int(dur * sr))
        let kickS = kick(sr)
        let snareS = snare(&rng, sr)
        let root = 36 + (notes[key] ?? 9)
        let prog = minor ? [0, 8, 3, 10] : [0, 7, 9, 5]
        let third = minor ? 3 : 4
        var truth = Truth(beats: [], downbeats: [], sections: [])
        var barI = 0
        for sec in secs {
            let s0 = Double(barI * 4) * beat
            let energy = sec.energy
            for _ in 0..<sec.bars {
                let barT = Double(barI * 4) * beat
                truth.downbeats.append(barT)
                let chordRoot = Double(root + prog[barI % 4])
                for q in 0..<4 {
                    let bt = barT + Double(q) * beat + (q % 2 == 1 ? swing * beat * 0.5 : 0)
                    truth.beats.append(bt)
                    let at = Int(bt * sr)
                    if energy >= 0.25 && (q == 0 || q == 2 || energy > 0.85) { add(&buf, kickS, at, 0.9 * min(1.0, energy + 0.2)) }
                    if energy >= 0.45 && (q == 1 || q == 3) { add(&buf, snareS, at, 0.45) }
                    if energy >= 0.35 {
                        let hats = energy < 0.8 ? 2 : 4
                        for h in 0..<hats {
                            let hit = hat(&rng, sr)
                            add(&buf, hit, at + Int(Double(h) * beat / Double(hats) * sr), 0.6)
                        }
                    }
                    let bassLen = beat * 0.9
                    let saw = tone(midiHz(chordRoot - 12), bassLen, "saw", sr)
                    let e = env(Int(bassLen * sr), 0.005, beat * 0.6, sr)
                    add(&buf, zip(saw, e).map { $0 * $1 }, at, 0.18 + 0.12 * energy)
                }
                let padLen = 4 * beat
                for iv in [0, third, 7] {
                    let s = tone(midiHz(chordRoot + 12 + Double(iv)), padLen, "sine", sr)
                    let e = env(Int(padLen * sr), 0.15, padLen * 0.9, sr)
                    add(&buf, zip(s, e).map { $0 * $1 }, Int(barT * sr), 0.06 + 0.04 * (1 - energy))
                }
                if energy >= 0.8 {
                    for e8 in 0..<8 {
                        let note = chordRoot + 24 + Double([0, third, 7, 12][e8 % 4])
                        let ln = beat / 2
                        let sq = tone(midiHz(note), ln, "square", sr)
                        let e = env(Int(ln * sr), 0.003, ln * 0.4, sr)
                        add(&buf, zip(sq, e).map { $0 * $1 }, Int((barT + Double(e8) * beat / 2) * sr), 0.05)
                    }
                }
                if vocalHum && energy >= 0.5 {
                    let ln = 2 * beat
                    let f0 = midiHz(chordRoot + 24 + Double(third))
                    let n = Int(ln * sr)
                    let e = env(n, 0.05, ln, sr)
                    let voice: [Float] = (0..<n).map { i in
                        let t = Double(i) / sr
                        let vib = sin(2 * Double.pi * 5.5 * t) * 4
                        let s7 = sin(2 * Double.pi * 700 * t)
                        let v = sin(2 * Double.pi * (f0 + vib) * t) * (0.6 + 0.4 * s7 * s7)
                        return Float(v * Double(e[i]))
                    }
                    add(&buf, voice, Int(barT * sr), 0.08)
                }
                barI += 1
            }
            truth.sections.append((sec.label, s0, Double(barI * 4) * beat, energy))
        }
        let tail = Int(1.5 * sr)
        for i in 0..<tail {                                    // np.linspace(1, 0, tail, dtype=float32)
            let fade: Float = i == tail - 1 ? 0 : Float(Double(i) * (-1.0 / Double(tail - 1)) + 1.0)
            buf[buf.count - tail + i] *= fade
        }
        let peak = buf.map(abs).max() ?? 0
        let scale = Float(max(1e-6, Double(peak)) / 0.8)
        for i in buf.indices { buf[i] /= scale }
        return (buf, truth)
    }
}
