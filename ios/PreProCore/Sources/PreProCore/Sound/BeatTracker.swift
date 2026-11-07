import Accelerate
import Foundation

/// Where a song's beats are — librosa's onset_strength, tempo and beat_track (tightness 120) as the desktop's
/// analyze/sound.py `music_info` runs them on 22.05 kHz mono, then its 70–180 BPM folding. Ported to the step:
/// fed the same onset envelope, it lands on librosa's exact beat frames (BeatParityTests).
public enum BeatTracker {
    public static let sampleRate = 22050.0
    public static let hop = 512

    public struct Beats: Equatable, Sendable {
        public var bpm: Double                     // after folding into 70–180
        public var frames: [Int]
        public var times: [Double] { frames.map { Double($0 * BeatTracker.hop) / BeatTracker.sampleRate } }
    }

    /// The song's tempo and beats, the desktop's way (a tempo above 180 halves, below 70 doubles with the beats between).
    public static func track(_ y: [Float]) -> Beats {
        let onset = onsetStrength(y)
        let bpm = tempo(onset)
        var frames = beatFrames(onset, bpm: bpm)
        var folded = bpm
        while folded > 180 {
            folded /= 2
            frames = stride(from: 0, to: frames.count, by: 2).map { frames[$0] }
        }
        while folded > 0 && folded < 70 {
            folded *= 2
            let mids = zip(frames, frames.dropFirst()).map { Int((Double($0 + $1) / 2).rounded(.down)) }
            frames = Array(Set(frames + mids)).sorted()
        }
        return Beats(bpm: folded, frames: frames)
    }

    /// librosa.onset.onset_strength: the mean rise of the mel spectrogram in decibels from one frame to the next
    /// (128 bands, n_fft 2048, hop 512), centred like librosa (frame t holds the rise into frame t − 2), float32.
    public static func onsetStrength(_ y: [Float], sr: Double = 22050, nFFT: Int = 2048) -> [Float] {
        let spec = DSP.powerSpectrogram(y, nFFT: nFFT, hop: hop)
        let mel = DSP.melSpectrogram(spec, filters: DSP.melFilters(sr: sr, nFFT: nFFT, nMels: 128, fmax: sr / 2), nMels: 128)
        let db = DSP.powerToDb(mel)
        let frames = spec.frames
        var onset = [Float](repeating: 0, count: frames)
        guard frames > 3 else { return onset }
        for t in 3..<frames {
            var acc: Float = 0                                 // numpy's mean over bands: a running float32 sum
            for m in 0..<128 {
                let row = m * frames
                acc += max(0, db[row + t - 2] - db[row + t - 3])
            }
            onset[t] = acc / 128
        }
        return onset
    }

    /// librosa.feature.tempo: an autocorrelation tempogram (8 s windows, periodic Hann, centred with linear ramps to
    /// zero, each window normalised to its peak) averaged over the song, weighed by a log-normal prior around 120 BPM,
    /// nothing above 320 BPM. The answer is one of the tempogram's bins: 60·sr / (hop·k).
    public static func tempo(_ onset: [Float], sr: Double = 22050, startBpm: Double = 120) -> Double {
        let win = Int(8.0 * sr) / hop
        let n = onset.count
        guard n > 0 else { return startBpm }
        let half = win / 2
        var padded = [Float](repeating: 0, count: n + 2 * half)
        let stepL = Double(onset[0]) / Double(half), stepR = Double(onset[n - 1]) / Double(half)
        for i in 0..<half {                                    // np.pad(mode="linear_ramp", end_values=0)
            padded[i] = Float(Double(i) * stepL)
            padded[n + 2 * half - 1 - i] = Float(Double(i) * stepR)
        }
        for i in 0..<n { padded[half + i] = onset[i] }
        let window = DSP.hann(win)
        var tg = [Double](repeating: 0, count: win)
        var frame = [Double](repeating: 0, count: win)
        var ac = [Double](repeating: 0, count: win)
        for t in 0..<n {
            for i in 0..<win { frame[i] = Double(padded[t + i]) * window[i] }
            frame.withUnsafeBufferPointer { fp in
                for lag in 0..<win {
                    var s = 0.0
                    vDSP_dotprD(fp.baseAddress!, 1, fp.baseAddress! + lag, 1, &s, vDSP_Length(win - lag))
                    ac[lag] = s
                }
            }
            let peak = ac.map(abs).max() ?? 0
            let norm = peak < Double.leastNormalMagnitude ? 1 : peak
            for lag in 0..<win { tg[lag] += ac[lag] / norm }
        }
        var best = -1
        var bestScore = -Double.infinity
        for k in 1..<win {
            let bpm = 60.0 * sr / (Double(hop) * Double(k))
            guard bpm < 320 else { continue }
            let d = log2(bpm) - log2(startBpm)
            let score = log1p(1e6 * (tg[k] / Double(n))) + -0.5 * d * d
            if score > bestScore {
                bestScore = score
                best = k
            }
        }
        return best > 0 ? 60.0 * sr / (Double(hop) * Double(best)) : startBpm
    }

    /// librosa's dynamic-programming beat tracker (Ellis 2007) at a fixed tempo: a local score (the envelope over its
    /// standard deviation, smoothed by a Gaussian a beat wide), the best chain of beats about one period apart, the
    /// weak beats at either end trimmed. Kept to librosa's numba code: float32 scores, double-precision steps.
    public static func beatFrames(_ onset: [Float], bpm: Double, sr: Double = 22050, tightness: Double = 120, trim: Bool = true) -> [Int] {
        guard onset.contains(where: { $0 != 0 }), bpm > 0 else { return [] }
        let n = onset.count
        let fpb = (sr / Double(hop) * 60.0 / bpm).rounded(.toNearestOrEven)
        let f32 = Float(fpb)
        let sd = DSP.std(onset, ddof: 1)
        let norm = onset.map { $0 / (sd + Float.leastNormalMagnitude) }
        let f = Int(fpb)
        let window = (-f...f).map { j -> Double in
            let x = Double(j) * 32.0 / Double(f32)
            return exp(-0.5 * x * x)
        }
        let K = window.count
        var local = [Float](repeating: 0, count: n)
        for i in 0..<n {
            var acc: Float = 0
            let lo = max(0, i + K / 2 - n + 1), hi = min(i + K / 2, K)
            if lo < hi {
                for k in lo..<hi { acc = Float(Double(acc) + window[k] * Double(norm[i + K / 2 - k])) }
            }
            local[i] = acc
        }
        // the dynamic program
        let threshold0 = 0.01 * Double(local.max() ?? 0)
        let back = Int(Double(f32 / 2).rounded(.toNearestOrEven))
        let logFpb = Double(logf(f32))
        var backlink = [Int](repeating: -1, count: n)
        var cum = [Float](repeating: 0, count: n)
        var firstBeat = true
        for i in 0..<n {
            var best = -Double.infinity
            var at = -1
            var loc = i - back
            let stop = Int(Double(i) - 2 * Double(f32) - 1)
            while loc > stop && loc >= 0 {
                let d = log(Double(i - loc)) - logFpb
                let score = Double(cum[loc]) - tightness * d * d
                if score > best {
                    best = score
                    at = loc
                }
                loc -= 1
            }
            cum[i] = at >= 0 ? Float(Double(local[i]) + best) : local[i]
            if firstBeat && Double(local[i]) < threshold0 {
                backlink[i] = -1
            } else {
                backlink[i] = at
                firstBeat = false
            }
        }
        // the last beat: the latest local maximum of the cumulative score that reaches half the maxima's median
        var isMax = [Bool](repeating: false, count: n)
        for i in 0..<n {
            let prev = i > 0 ? cum[i - 1] : cum[0]
            let next = i + 1 < n ? cum[i + 1] : cum[n - 1]
            isMax[i] = cum[i] > prev && cum[i] >= next
        }
        let maxima = (0..<n).filter { isMax[$0] }.map { cum[$0] }.sorted()
        var median: Float = 0
        if !maxima.isEmpty {
            let h = maxima.count / 2
            median = maxima.count % 2 == 1 ? maxima[h] : (maxima[h - 1] + maxima[h]) / 2
        }
        let lastThreshold = 0.5 * median
        var tail = n - 1
        var j = n - 1
        while j >= 0 {
            if isMax[j] && cum[j] >= lastThreshold {
                tail = j
                break
            }
            j -= 1
        }
        var beat = [Bool](repeating: false, count: n)
        var b = tail
        while b >= 0 {
            beat[b] = true
            b = backlink[b]
        }
        // trim the weak beats at the ends: below half the RMS of the smoothed beat scores (np.convolve with a
        // 5-point Hann, sliced [2 : n + 2] exactly as librosa slices it)
        let scores = (0..<n).filter { beat[$0] }.map { Double(local[$0]) }
        let w = [0.0, 0.5, 1.0, 0.5, 0.0]
        var full = [Double](repeating: 0, count: scores.count + w.count - 1)
        for (a, s) in scores.enumerated() {
            for (k, wk) in w.enumerated() { full[a + k] += s * wk }
        }
        let smooth = full.count > 2 ? Array(full[2..<min(n + 2, full.count)]) : []
        let trimAt = trim && !smooth.isEmpty ? 0.5 * (smooth.map { $0 * $0 }.reduce(0, +) / Double(smooth.count)).squareRoot() : 0
        var a = 0
        while a < n && Double(local[a]) <= trimAt {
            beat[a] = false
            a += 1
        }
        var z = n - 1
        while z >= 0 && Double(local[z]) <= trimAt {
            beat[z] = false
            z -= 1
        }
        return (0..<n).filter { beat[$0] }
    }
}
