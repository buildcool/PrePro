import Foundation

/// A song as the edit needs it — the desktop's analyze/sound.py `music_info`, ported: the tempo and beats
/// (BeatTracker), the bar lines (the beat phase where chords change and the bass is heaviest), a 2 Hz energy curve,
/// the sections (intro, build, drop, chorus, break, outro, verse), key and mode, brightness and mood tags. Two known
/// simplifications: chroma assumes concert tuning (the desktop estimates it; on the test songs it changes nothing), and
/// the key comes from a 4096-point STFT chroma instead of a constant-Q one (the same mode; on an ambiguous Am–F–C–G song
/// the desktop says F major where the phone says C major).
public enum MusicAnalysis {
    static let major: [Double] = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    static let minor: [Double] = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
    static let keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    /// 22.05 kHz mono samples → the music analysis the edit plans on.
    public static func analyze(_ samples: [Float], sr: Double = 22050) -> MusicInfo {
        guard Double(samples.count) >= sr * 2 else {
            return MusicInfo(bpm: 0, beats: [], downbeats: [], sections: [], energyCurve: [], key: nil, mode: nil, vocals: nil,
                             moodTags: [], brightness: 0)                 // the desktop's empty MusicInfo()
        }
        let y = Array(samples.prefix(Int(sr * 600)))
        let beats = BeatTracker.track(y)
        let times = beats.times
        let downbeats = barLines(y, sr: sr, frames: beats.frames, times: times)
        let curve = energyCurve(y, sr: sr)
        let dur = Double(y.count) / sr
        let sections = self.sections(y, sr: sr, curve: curve, downbeats: downbeats, dur: dur)
        let (key, mode) = keyAndMode(Array(y.prefix(Int(sr * 120))), sr: sr)
        let bright = min(1.0, centroid(Array(y.prefix(Int(sr * 60))), sr: sr) / 4000.0)
        var info = MusicInfo(bpm: Py.round(beats.bpm, 2), beats: times.map { Py.round($0, 3) }, downbeats: downbeats.map { Py.round($0, 3) },
                             sections: sections, energyCurve: curve.map { Py.round(Double($0), 3) }, key: key, mode: mode, vocals: nil,
                             moodTags: [], brightness: Py.round(bright, 3))
        info.moodTags = moodTags(info)
        return info
    }

    // MARK: bar lines

    /// Which beat of four starts the bar: chords change on the bar line and the kick is heaviest there. Low end alone
    /// can't tell beat 1 from beat 3 when the kick plays both, so the harmonic change entering each beat decides, with
    /// the energy below 150 Hz as the tie-break.
    static func barLines(_ y: [Float], sr: Double, frames: [Int], times: [Double]) -> [Double] {
        let s = DSP.magnitudeSpectrogram(y, nFFT: 2048, hop: 512)
        let T = s.frames, bins = s.bins
        let lowBins = (0..<bins).filter { Double($0) * (sr / 2) / Double(bins - 1) < 150 }
        let low: [Float] = (0..<T).map { t in
            var acc: Float = 0
            for k in lowBins { acc += s.power[t * bins + k] }
            return acc
        }
        let bidx = frames.filter { $0 < T }
        var change = [Double](repeating: 0, count: bidx.count)
        if bidx.count > 8 {
            let ch = DSP.chroma((T, bins, s.power.map { $0 * $0 }), sr: sr, nFFT: 2048)
            let ends = Array(bidx.dropFirst()) + [T]
            var cs: [[Float]] = []
            for (a, b) in zip(bidx, ends) {
                var v = (0..<12).map { c in DSP.median((a..<max(a + 1, b)).map { ch[c * T + $0] }) }
                let norm = v.map { $0 * $0 }.reduce(Float(0), +).squareRoot() + 1e-9
                v = v.map { $0 / norm }
                cs.append(v)
            }
            for i in 1..<cs.count {
                let d = (0..<12).map { cs[i][$0] - cs[i - 1][$0] }
                change[i] = Double(d.map { $0 * $0 }.reduce(Float(0), +).squareRoot())
            }
        }
        var lows = [Double](repeating: 0, count: 4), chords = [Double](repeating: 0, count: 4)
        for ph in 0..<4 {
            let idx = Array(stride(from: ph, to: bidx.count, by: 4))
            if !idx.isEmpty {
                let vals = idx.map { low[bidx[$0]] }
                lows[ph] = Double(DSP.pairwiseSum(vals[...]) / Float(vals.count))
            }
            if idx.count > 1 {
                let cv = Array(idx.map { change[$0] }.dropFirst(ph == 0 ? 1 : 0))
                chords[ph] = cv.isEmpty ? .nan : cv.reduce(0, +) / Double(cv.count)
            }
        }
        let maxLow = lows.max() ?? 0, maxChord = chords.max() ?? 0
        let score = (0..<4).map { 0.5 * lows[$0] / (maxLow + 1e-9) + chords[$0] / (maxChord + 1e-9) }
        let any = lows.contains { $0 != 0 } || chords.contains { $0 != 0 }
        let ph = any ? score.indices.max(by: { score[$0] < score[$1] || (score[$0] == score[$1] && $0 > $1) }) ?? 0 : 0
        return stride(from: ph, to: times.count, by: 4).map { times[$0] }
    }

    // MARK: energy

    /// Loudness every half second, scaled between the song's quiet (5th percentile) and loud (98th) parts, 0…1.
    static func energyCurve(_ y: [Float], sr: Double) -> [Float] {
        let hop = Int(sr) / 2
        let n = y.count / hop
        guard n > 0 else { return [] }
        let rms: [Float] = (0..<n).map { i in
            let sq = y[(i * hop)..<((i + 1) * hop)].map { $0 * $0 }
            return (DSP.pairwiseSum(sq[...]) / Float(hop)).squareRoot()
        }
        let lo = DSP.percentile(rms, 5), hi = DSP.percentile(rms, 98)
        let span = (hi - lo) + Float(1e-9)
        return rms.map { min(max(($0 - lo) / span, 0), 1) }
    }

    // MARK: sections

    /// The song's parts: bounds from clustering timbre, harmony and loudness (Ward, neighbours only), snapped to bar
    /// lines, parts under 4 s merged, then named by their energy: the strongest is the drop (or chorus), the one before
    /// it the build, a quiet start the intro, a quiet end the outro, a dip a break.
    static func sections(_ y: [Float], sr: Double, curve: [Float], downbeats: [Double], dur: Double) -> [Section] {
        let k = Int(min(max((dur / 8).rounded(.toNearestOrEven), 3), 8))
        let hop = 2048
        let mf = DSP.mfcc(y, sr: sr, n: 13, nFFT: 2048, hop: hop)
        let spec = DSP.powerSpectrogram(y, nFFT: 2048, hop: hop)
        let ch = DSP.chroma(spec, sr: sr, nFFT: 2048)
        let rm = DSP.rms(y, frame: 2048, hop: hop).map { $0 * 30 }
        let T = mf.frames
        let mfStd = DSP.std(mf.coeffs, ddof: 0)
        var feats = [[Double]](repeating: [], count: T)
        for t in 0..<T {
            var v: [Double] = []
            v.reserveCapacity(26)
            for c in 0..<13 { v.append(Double(mf.coeffs[c * T + t] / (mfStd + Float(1e-9)))) }
            for c in 0..<12 { v.append(Double(ch[c * T + t])) }
            v.append(Double(t < rm.count ? rm[t] : 0))
            feats[t] = v
        }
        let starts = wardSegments(feats, k: k)
        var btimes = Array(Set([0.0] + starts.map { Double($0 * hop) / sr } + [dur])).sorted()
        if !downbeats.isEmpty {
            var snapped = [0.0]
            for b in btimes.dropFirst().dropLast() {
                let j = downbeats.indices.min(by: { abs(downbeats[$0] - b) < abs(downbeats[$1] - b) }) ?? 0
                snapped.append(downbeats[j])
            }
            snapped.append(dur)
            btimes = Array(Set(snapped.map { Py.round($0, 3) })).sorted()
        }
        var merged = [btimes[0]]
        for b in btimes.dropFirst() {
            if b - merged[merged.count - 1] < 4.0 && b != btimes[btimes.count - 1] { continue }
            merged.append(b)
        }
        if merged[merged.count - 1] != btimes[btimes.count - 1] { merged[merged.count - 1] = btimes[btimes.count - 1] }
        var secs: [Section] = []
        for (a, b) in zip(merged, merged.dropFirst()) {
            let i0 = Int(a * 2), i1 = max(Int(a * 2) + 1, Int(b * 2))
            let part = Array(curve[min(i0, curve.count)..<min(i1, curve.count)])
            let e = part.isEmpty ? 0 : Double(DSP.pairwiseSum(part[...]) / Float(part.count))
            secs.append(Section(t0: Py.round(a, 3), t1: Py.round(b, 3), label: "verse", energy: Py.round(e, 3)))
        }
        guard !secs.isEmpty else { return [] }
        let es = secs.map(\.energy)
        let lo = es.min()!, hi = es.max()!
        let rel = es.map { ($0 - lo) / (hi - lo + 1e-9) }
        let top = es.indices.max(by: { es[$0] < es[$1] || (es[$0] == es[$1] && $0 > $1) })!
        let contrast = hi - lo
        for i in secs.indices {
            if i == top && contrast > 0.12 {
                secs[i].label = contrast > 0.3 && es[top] > 0.5 ? "drop" : "chorus"
            } else if i + 1 == top && contrast > 0.12 && rel[i] < 0.85 {
                secs[i].label = "build"
            } else if i == 0 && rel[i] < 0.5 {
                secs[i].label = "intro"
            } else if i == secs.count - 1 && rel[i] < 0.5 {
                secs[i].label = "outro"
            } else if rel[i] < 0.3 {
                secs[i].label = "break"
            } else {
                secs[i].label = "verse"
            }
        }
        return secs
    }

    /// Ward clustering of frames where only neighbours may merge (scikit-learn's AgglomerativeClustering on a chain):
    /// the pair whose merge adds least variance merges first, until k parts remain. Returns each part's first frame.
    static func wardSegments(_ x: [[Double]], k: Int) -> [Int] {
        guard !x.isEmpty else { return [0] }
        var start = Array(x.indices), count = [Int](repeating: 1, count: x.count), sum = x
        func cost(_ i: Int) -> Double {                           // merging part i with part i + 1
            let n = Double(count[i] * count[i + 1]) / Double(count[i] + count[i + 1])
            var d = 0.0
            for f in sum[i].indices {
                let diff = sum[i][f] / Double(count[i]) - sum[i + 1][f] / Double(count[i + 1])
                d += diff * diff
            }
            return d * n
        }
        var costs = (0..<(x.count - 1)).map(cost)
        while start.count > max(k, 1) {
            guard let i = costs.indices.min(by: { costs[$0] < costs[$1] }) else { break }
            count[i] += count[i + 1]
            for f in sum[i].indices { sum[i][f] += sum[i + 1][f] }
            start.remove(at: i + 1)
            count.remove(at: i + 1)
            sum.remove(at: i + 1)
            costs.remove(at: i)
            if i < costs.count { costs[i] = cost(i) }
            if i > 0 { costs[i - 1] = cost(i - 1) }
        }
        return start
    }

    // MARK: key, brightness, mood

    static func keyAndMode(_ y: [Float], sr: Double) -> (String, String) {
        let spec = DSP.powerSpectrogram(y, nFFT: 4096, hop: 512)
        let ch = DSP.chroma(spec, sr: sr, nFFT: 4096)
        let T = spec.frames
        let mean = (0..<12).map { c -> Double in
            var s = 0.0
            for t in 0..<T { s += Double(ch[c * T + t]) }
            return T > 0 ? s / Double(T) : 0
        }
        var best = (-2.0, "C", "major")
        for k in 0..<12 {
            for (prof, mode) in [(major, "major"), (minor, "minor")] {
                let rolled = (0..<12).map { prof[(($0 - k) % 12 + 12) % 12] }
                let c = correlation(rolled, mean)
                if c > best.0 { best = (c, keys[k], mode) }
            }
        }
        return (best.1, best.2)
    }

    static func correlation(_ a: [Double], _ b: [Double]) -> Double {
        let ma = a.reduce(0, +) / Double(a.count), mb = b.reduce(0, +) / Double(b.count)
        var num = 0.0, da = 0.0, db = 0.0
        for i in a.indices {
            num += (a[i] - ma) * (b[i] - mb)
            da += (a[i] - ma) * (a[i] - ma)
            db += (b[i] - mb) * (b[i] - mb)
        }
        return da > 0 && db > 0 ? num / (da * db).squareRoot() : .nan
    }

    /// The mean spectral centroid in Hz (librosa.feature.spectral_centroid).
    static func centroid(_ y: [Float], sr: Double) -> Double {
        let s = DSP.magnitudeSpectrogram(y, nFFT: 2048, hop: 512)
        guard s.frames > 0 else { return 0 }
        var total = 0.0
        for t in 0..<s.frames {
            var sum = 0.0, weighted = 0.0
            for k in 0..<s.bins { sum += Double(s.power[t * s.bins + k]) }
            if sum >= Double(Float.leastNormalMagnitude) {
                for k in 0..<s.bins { weighted += (Double(k) * (sr / 2) / Double(s.bins - 1)) * (Double(s.power[t * s.bins + k]) / sum) }
            }
            total += weighted
        }
        return total / Double(s.frames)
    }

    /// Words a creator would search a library with (analyze/sound.py mood_tags).
    public static func moodTags(_ m: MusicInfo) -> [String] {
        let e = m.energyCurve.isEmpty ? 0.5 : m.energyCurve.reduce(0, +) / Double(m.energyCurve.count)
        var tags: [String] = []
        if m.bpm < 95 && e < 0.55 { tags += ["chill", "calm"] }
        if m.bpm >= 125 && e > 0.5 { tags += ["hype", "energetic"] }
        if m.mode == "major" && 95 <= m.bpm && m.bpm < 135 { tags += ["happy", "upbeat"] }
        if m.mode == "minor" && m.bpm < 100 { tags += ["moody"] }
        let hasDrop = m.sections.contains { $0.label == "drop" }
        if hasDrop && m.bpm >= 100 && (m.sections.map(\.energy).max() ?? 0) >= 0.75 {
            tags += ["epic", "build-drop"]
        } else if hasDrop {
            tags += ["build-drop"]
        }
        if m.brightness < 0.25 && e < 0.5 { tags += ["warm", "aesthetic"] }
        let out = Array(Set(tags)).sorted(by: Py.less)
        return out.isEmpty ? ["neutral"] : out
    }
}
