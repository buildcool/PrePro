import Accelerate
import Foundation

/// librosa's spectral front end, ported with Accelerate and kept to librosa's own precision: the window and the FFT in
/// double precision, the spectrum stored as float32 (librosa's complex64), mel weights and decibels in float32 — so the
/// phone hears a song the way the desktop does.
enum DSP {
    /// A periodic Hann window computed the way scipy's get_window("hann", n, fftbins=True) does: 0.5 + 0.5·cos(fac) over
    /// fac = linspace(−π, π, n + 1), the last point dropped (to the last bit, unlike 0.5 − 0.5·cos(2πk/n)).
    static func hann(_ n: Int) -> [Double] {
        let step = (Double.pi - -Double.pi) / Double(n)
        return (0..<n).map { 0.5 + 0.5 * cos(Double($0) * step + -Double.pi) }
    }

    /// One real FFT size, reused frame after frame.
    final class RealFFT {
        let n: Int
        private let log2n: vDSP_Length
        private let setup: FFTSetupD

        init(_ n: Int) {
            precondition(n > 1 && n & (n - 1) == 0, "FFT size must be a power of two")
            self.n = n
            log2n = vDSP_Length(Int(log2(Double(n))))
            setup = vDSP_create_fftsetupD(log2n, FFTRadix(kFFTRadix2))!
        }

        deinit { vDSP_destroy_fftsetupD(setup) }

        /// The DFT X[0…n/2] of a real signal (re, im), unscaled like numpy's rfft (vDSP returns twice the DFT).
        func forward(_ x: [Double]) -> (re: [Double], im: [Double]) {
            let half = n / 2
            var re = [Double](repeating: 0, count: half)
            var im = [Double](repeating: 0, count: half)
            re.withUnsafeMutableBufferPointer { rp in
                im.withUnsafeMutableBufferPointer { ip in
                    var split = DSPDoubleSplitComplex(realp: rp.baseAddress!, imagp: ip.baseAddress!)
                    x.withUnsafeBufferPointer { xp in
                        xp.baseAddress!.withMemoryRebound(to: DSPDoubleComplex.self, capacity: half) {
                            vDSP_ctozD($0, 2, &split, 1, vDSP_Length(half))
                        }
                    }
                    vDSP_fft_zripD(setup, &split, 1, log2n, FFTDirection(FFT_FORWARD))
                }
            }
            var outRe = [Double](repeating: 0, count: half + 1)
            var outIm = [Double](repeating: 0, count: half + 1)
            outRe[0] = re[0] / 2                     // DC and Nyquist come packed in the first slot
            outRe[half] = im[0] / 2
            for k in 1..<half {
                outRe[k] = re[k] / 2
                outIm[k] = im[k] / 2
            }
            return (outRe, outIm)
        }
    }

    /// Frames of |STFT|² (librosa's _spectrogram(power=2)): the magnitude, squared in float32.
    static func powerSpectrogram(_ y: [Float], nFFT: Int = 2048, hop: Int = 512) -> (frames: Int, bins: Int, power: [Float]) {
        let s = magnitudeSpectrogram(y, nFFT: nFFT, hop: hop)
        return (s.frames, s.bins, s.power.map { $0 * $0 })
    }

    /// Frames of |STFT|: centred (n_fft/2 zeros each side), a periodic Hann window, the FFT in double precision and
    /// the magnitude in float32 (|complex64|, as numpy takes it). frames × (n_fft/2 + 1), row-major by frame.
    static func magnitudeSpectrogram(_ y: [Float], nFFT: Int = 2048, hop: Int = 512) -> (frames: Int, bins: Int, power: [Float]) {
        let pad = nFFT / 2
        var padded = [Double](repeating: 0, count: y.count + 2 * pad)
        for (i, v) in y.enumerated() { padded[pad + i] = Double(v) }
        let frames = 1 + (padded.count - nFFT) / hop
        let bins = nFFT / 2 + 1
        let window = hann(nFFT)
        let fft = RealFFT(nFFT)
        var power = [Float](repeating: 0, count: frames * bins)
        var frame = [Double](repeating: 0, count: nFFT)
        for t in 0..<frames {
            let start = t * hop
            for i in 0..<nFFT { frame[i] = window[i] * padded[start + i] }
            let (re, im) = fft.forward(frame)
            for k in 0..<bins { power[t * bins + k] = hypotf(Float(re[k]), Float(im[k])) }
        }
        return (frames, bins, power)
    }

    // MARK: mel

    static func hzToMel(_ f: Double) -> Double {
        let fSp = 200.0 / 3, minLogHz = 1000.0, minLogMel = minLogHz / fSp, logstep = log(6.4) / 27.0
        return f >= minLogHz ? minLogMel + log(f / minLogHz) / logstep : f / fSp
    }

    static func melToHz(_ m: Double) -> Double {
        let fSp = 200.0 / 3, minLogHz = 1000.0, minLogMel = minLogHz / fSp, logstep = log(6.4) / 27.0
        return m >= minLogMel ? minLogHz * exp(logstep * (m - minLogMel)) : fSp * m
    }

    /// librosa.filters.mel (Slaney scale and area normalisation), float32: nMels × (n_fft/2 + 1), row-major.
    static func melFilters(sr: Double, nFFT: Int, nMels: Int = 128, fmin: Double = 0, fmax: Double? = nil) -> [Float] {
        let bins = nFFT / 2 + 1
        let top = fmax ?? sr / 2
        let fftFreqs = (0..<bins).map { Double($0) * (sr / 2) / Double(bins - 1) }       // np.linspace(0, sr/2, bins)
        let lo = hzToMel(fmin), hi = hzToMel(top)
        let step = (hi - lo) / Double(nMels + 1)                                         // np.linspace, to the bit
        let melF = (0..<(nMels + 2)).map { melToHz($0 == nMels + 1 ? hi : Double($0) * step + lo) }
        var w = [Float](repeating: 0, count: nMels * bins)
        for i in 0..<nMels {
            let enorm = 2.0 / (melF[i + 2] - melF[i])
            let d0 = melF[i + 1] - melF[i], d1 = melF[i + 2] - melF[i + 1]
            for k in 0..<bins {
                let lower = -(melF[i] - fftFreqs[k]) / d0
                let upper = (melF[i + 2] - fftFreqs[k]) / d1
                let v = Float(max(0, min(lower, upper)))                                  // stored float32 …
                w[i * bins + k] = Float(Double(v) * enorm)                                // … then scaled in double
            }
        }
        return w
    }

    /// Mel power spectrogram: nMels × frames, row-major by band (librosa's layout).
    static func melSpectrogram(_ spec: (frames: Int, bins: Int, power: [Float]), filters: [Float], nMels: Int = 128) -> [Float] {
        // (nMels × bins) · (bins × frames): the spectrogram is frames × bins, so transpose it first
        var specT = [Float](repeating: 0, count: spec.bins * spec.frames)
        vDSP_mtrans(spec.power, 1, &specT, 1, vDSP_Length(spec.bins), vDSP_Length(spec.frames))
        var mel = [Float](repeating: 0, count: nMels * spec.frames)
        vDSP_mmul(filters, 1, specT, 1, &mel, 1, vDSP_Length(nMels), vDSP_Length(spec.frames), vDSP_Length(spec.bins))
        return mel
    }

    /// librosa.power_to_db (ref 1.0, amin 1e-10, top_db 80), float32.
    static func powerToDb(_ s: [Float], topDb: Float = 80) -> [Float] {
        var db = s.map { 10 * log10f(max(1e-10, $0)) }
        if let peak = db.max() {
            let floor = peak - topDb
            for i in db.indices where db[i] < floor { db[i] = floor }
        }
        return db
    }

    // MARK: chroma, MFCC, RMS

    /// librosa.filters.chroma (tuning 0, centred on octave 5 with an octave width of 2, columns L2-normalised, C first),
    /// float32: 12 × (n_fft/2 + 1), row-major.
    static func chromaFilters(sr: Double, nFFT: Int, ctroct: Double = 5.0, octwidth: Double = 2) -> [Float] {
        let nC = 12, bins = nFFT / 2 + 1
        let step = sr / Double(nFFT)
        var frq = [Double](repeating: 0, count: nFFT)
        for i in 1..<nFFT { frq[i] = Double(nC) * log2((Double(i) * step) / (440.0 / 16)) }
        frq[0] = frq[1] - 1.5 * Double(nC)
        var width = [Double](repeating: 1, count: nFFT)
        for i in 0..<(nFFT - 1) { width[i] = max(frq[i + 1] - frq[i], 1.0) }
        let half = (Double(nC) / 2).rounded(.toNearestOrEven)
        var w = [Double](repeating: 0, count: nC * nFFT)
        for c in 0..<nC {
            for f in 0..<nFFT {
                let x = frq[f] - Double(c) + half + 10 * Double(nC)
                var r = fmod(x, Double(nC))                         // np.remainder: the sign of the divisor
                if r != 0 && r < 0 { r += Double(nC) }
                let d = r - half
                let z = 2 * d / width[f]
                w[c * nFFT + f] = exp(-0.5 * z * z)
            }
        }
        for f in 0..<nFFT {                                         // each frequency: unit L2 over the 12 classes
            var ss = 0.0
            for c in 0..<nC { ss += w[c * nFFT + f] * w[c * nFFT + f] }
            let len = ss.squareRoot()
            let g = (frq[f] / Double(nC) - ctroct) / octwidth
            let oct = exp(-0.5 * g * g)
            for c in 0..<nC { w[c * nFFT + f] = (len < Double.leastNormalMagnitude ? w[c * nFFT + f] : w[c * nFFT + f] / len) * oct }
        }
        var out = [Float](repeating: 0, count: nC * bins)
        for c in 0..<nC {
            let src = (c + 3) % nC                                  // np.roll(-3): A-based classes to C first
            for f in 0..<bins { out[c * bins + f] = Float(w[src * nFFT + f]) }
        }
        return out
    }

    /// Chroma (12 × frames, row-major): the filters applied to a power spectrogram, each frame scaled to its peak.
    static func chroma(_ spec: (frames: Int, bins: Int, power: [Float]), sr: Double, nFFT: Int) -> [Float] {
        let raw = melSpectrogram(spec, filters: chromaFilters(sr: sr, nFFT: nFFT), nMels: 12)
        var out = raw
        for t in 0..<spec.frames {
            var peak: Float = 0
            for c in 0..<12 { peak = max(peak, abs(raw[c * spec.frames + t])) }
            if peak >= Float.leastNormalMagnitude {
                for c in 0..<12 { out[c * spec.frames + t] = raw[c * spec.frames + t] / peak }
            }
        }
        return out
    }

    /// librosa.feature.mfcc: the orthonormal DCT-II of the log-mel spectrogram, the first `n` coefficients (n × frames).
    static func mfcc(_ y: [Float], sr: Double, n: Int = 13, nFFT: Int = 2048, hop: Int = 2048) -> (frames: Int, coeffs: [Float]) {
        let spec = powerSpectrogram(y, nFFT: nFFT, hop: hop)
        let db = powerToDb(melSpectrogram(spec, filters: melFilters(sr: sr, nFFT: nFFT, nMels: 128, fmax: sr / 2), nMels: 128))
        let m = 128, T = spec.frames
        var out = [Float](repeating: 0, count: n * T)
        for k in 0..<n {
            let scale = k == 0 ? (1.0 / Double(m)).squareRoot() : (2.0 / Double(m)).squareRoot()
            for t in 0..<T {
                var s = 0.0
                for i in 0..<m { s += Double(db[i * T + t]) * cos(Double.pi * Double(k) * (2 * Double(i) + 1) / (2 * Double(m))) }
                out[k * T + t] = Float(s * scale)
            }
        }
        return (T, out)
    }

    /// librosa.feature.rms: frames of `frame` samples every `hop`, centred with zeros (float32).
    static func rms(_ y: [Float], frame: Int = 2048, hop: Int = 2048) -> [Float] {
        let pad = frame / 2
        var padded = [Float](repeating: 0, count: y.count + 2 * pad)
        for (i, v) in y.enumerated() { padded[pad + i] = v }
        let frames = 1 + (padded.count - frame) / hop
        return (0..<frames).map { t in
            let sq = padded[(t * hop)..<(t * hop + frame)].map { $0 * $0 }
            return (pairwiseSum(sq[...]) / Float(frame)).squareRoot()
        }
    }

    /// np.percentile(x, q) for float32 (linear interpolation, numpy's two-sided lerp).
    static func percentile(_ x: [Float], _ q: Double) -> Float {
        let s = x.sorted()
        guard !s.isEmpty else { return .nan }
        let v = q / 100 * Double(s.count - 1)
        let lo = Int(v.rounded(.down)), hi = min(lo + 1, s.count - 1)
        let g = v - Double(lo)
        let diff = s[hi] - s[lo]
        return g >= 0.5 ? s[hi] - diff * Float(1 - g) : s[lo] + diff * Float(g)
    }

    /// np.median for float32 (the mean of the two middle values when the count is even).
    static func median(_ x: [Float]) -> Float {
        let s = x.sorted()
        guard !s.isEmpty else { return .nan }
        let h = s.count / 2
        return s.count % 2 == 1 ? s[h] : (s[h - 1] + s[h]) / 2
    }

    // MARK: numpy's float32 reductions

    /// numpy's pairwise summation for float32 (blocks of 8 lanes, 128-element leaves) — the last bit of np.sum/np.mean.
    static func pairwiseSum(_ a: ArraySlice<Float>) -> Float {
        let n = a.count, base = a.startIndex
        if n < 8 {
            var res: Float = 0
            for i in 0..<n { res += a[base + i] }
            return res
        }
        if n <= 128 {
            var r = (0..<8).map { a[base + $0] }
            var i = 8
            while i < n - (n % 8) {
                for j in 0..<8 { r[j] += a[base + i + j] }
                i += 8
            }
            var res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]))
            while i < n {
                res += a[base + i]
                i += 1
            }
            return res
        }
        var n2 = n / 2
        n2 -= n2 % 8
        return pairwiseSum(a[base..<(base + n2)]) + pairwiseSum(a[(base + n2)...])
    }

    /// np.std(x, ddof=1) of a float32 array, as numpy computes it in float32.
    static func std(_ x: [Float], ddof: Int = 1) -> Float {
        let mean = pairwiseSum(x[...]) / Float(x.count)
        let sq = x.map { ($0 - mean) * ($0 - mean) }
        return (pairwiseSum(sq[...]) / Float(x.count - ddof)).squareRoot()
    }
}
