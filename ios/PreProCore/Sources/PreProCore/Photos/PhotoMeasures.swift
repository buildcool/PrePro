import Foundation

/// What a still is judged by — the desktop's `photo_measures` (analyze/pipeline.py), to the bit, from the same upright
/// thumbnail: imagehash's perceptual hash, the mean colour, brightness, contrast, sharpness (a photo: its sharpest part),
/// the dark / blurry flags, quality and the striking score. numpy's float32 and pairwise sums, OpenCV's grey and
/// Laplacian, Pillow's grey and Lanczos are all reproduced as they compute.
public struct PhotoMeasures: Equatable, Sendable {
    public var phash: String
    public var color: [Double]
    public var brightness: Double
    public var contrast: Double
    public var sharpness: Double
    public var quality: Double
    public var flags: [String]
    public var aesthetic: Double
    /// Before rounding (for the parity tests).
    public var raw: Raw

    public struct Raw: Equatable, Sendable {
        public var brightness: Double
        public var contrast: Double
        public var sharpness: Double
        public var colourful: Double
    }

    public static func measure(_ img: Picture, faces: [FaceBox], photo: Bool = true) -> PhotoMeasures {
        precondition(img.channels == 3)
        let W = img.width, H = img.height, n = W * H
        // np.asarray(im, float32) / 255
        var arr = [Float](repeating: 0, count: n * 3)
        var grey = [UInt8](repeating: 0, count: n)
        img.pixels.withUnsafeBufferPointer { p in
            for i in 0..<(n * 3) { arr[i] = Float(p[i]) / 255 }
            for i in 0..<n {                                      // cv2.cvtColor(RGB2GRAY) of (arr·255).astype(uint8) = the pixels
                let r = UInt32(p[3 * i]), g = UInt32(p[3 * i + 1]), b = UInt32(p[3 * i + 2])
                grey[i] = UInt8((r * 9798 + g * 19235 + b * 3735 + 16384) >> 15)
            }
        }
        // the mean colour: arr.reshape(-1, 3).mean(axis=0), added pixel by pixel in float32
        var acc: [Float] = [0, 0, 0]
        for i in 0..<n {
            acc[0] += arr[3 * i]
            acc[1] += arr[3 * i + 1]
            acc[2] += arr[3 * i + 2]
        }
        let color = acc.map { Double($0 / Float(n)) }
        let bright = Double(DSP.pairwiseSum(arr[...]) / Float(n * 3))
        // cv2.Laplacian(grey, CV_64F): [0 1 0; 1 −4 1; 0 1 0], the border reflected (BORDER_REFLECT_101)
        var lap = [Double](repeating: 0, count: n)
        if W >= 2 && H >= 2 {
            func at(_ x: Int, _ y: Int) -> Int {
                let xx = x < 0 ? -x : (x >= W ? 2 * W - 2 - x : x)
                let yy = y < 0 ? -y : (y >= H ? 2 * H - 2 - y : y)
                return Int(grey[yy * W + xx])
            }
            for y in 0..<H {
                for x in 0..<W {
                    let s = at(x - 1, y) + at(x + 1, y) + at(x, y - 1) + at(x, y + 1)
                    lap[y * W + x] = Double(s - 4 * Int(grey[y * W + x]))
                }
            }
        }
        var sharp = variance(lap, W, 0, W, 0, H)
        // contrast: grey.std() / 255
        var gsum = 0
        for g in grey { gsum += Int(g) }
        let gmean = Double(gsum) / Double(n)
        let dev = grey.map { (Double($0) - gmean) * (Double($0) - gmean) }
        let contrast = (pairwiseSum(dev) / Double(n)).squareRoot() / 255.0
        // colourfulness, in float32 as numpy does it
        var rg = [Float](repeating: 0, count: n), yb = [Float](repeating: 0, count: n)
        for i in 0..<n {
            let r = arr[3 * i], g = arr[3 * i + 1], b = arr[3 * i + 2]
            rg[i] = r - g
            yb[i] = Float(0.5) * (r + g) - b
        }
        let rs = DSP.std(rg, ddof: 0), ys = DSP.std(yb, ddof: 0)
        let rm = DSP.pairwiseSum(rg[...]) / Float(n), ym = DSP.pairwiseSum(yb[...]) / Float(n)
        let colourful = Double((rs * rs + ys * ys).squareRoot() + Float(0.3) * (rm * rm + ym * ym).squareRoot())
        if photo {
            // as sharp as its sharpest part: the second sharpest of 4×4 tiles, or a face
            var tiles: [Double] = []
            for i in 0..<4 {
                for j in 0..<4 {
                    tiles.append(variance(lap, W, j * W / 4, (j + 1) * W / 4, i * H / 4, (i + 1) * H / 4))
                }
            }
            tiles.sort()
            var best = max(sharp, tiles[14])
            for b in faces where b.w * Double(W) >= 8 && b.h * Double(H) >= 8 {
                let y0 = max(0, Int((b.y - b.h / 2) * Double(H))), y1 = min(H, Int((b.y + b.h / 2) * Double(H)))
                let x0 = max(0, Int((b.x - b.w / 2) * Double(W))), x1 = min(W, Int((b.x + b.w / 2) * Double(W)))
                guard y1 > y0, x1 > x0 else { continue }                  // numpy: nan, which max() passes over
                best = max(best, variance(lap, W, x0, x1, y0, y1))
            }
            sharp = best
        }
        var flags: [String] = []
        if bright < 0.17 { flags.append("dark") }
        if sharp < (photo ? 20 : 25) { flags.append("blurry") }
        let q = max(0.0, 1.0 - 0.4 * (flags.contains("dark") ? 1 : 0) - 0.4 * (flags.contains("blurry") ? 1 : 0))
        let striking = Py.round(min(1.0, colourful * 2.2) * 0.35 + min(1.0, contrast * 4) * 0.25 + min(1.0, sharp / 400) * 0.2
                                + 0.2 * (faces.isEmpty ? 0 : 1), 3)
        return PhotoMeasures(phash: phash(img), color: color, brightness: Py.round(bright, 3), contrast: Py.round(contrast, 3),
                             sharpness: Py.round(sharp, 2), quality: Py.round(q, 3), flags: flags, aesthetic: striking,
                             raw: Raw(brightness: bright, contrast: contrast, sharpness: sharp, colourful: colourful))
    }

    /// np.var of a block [x0, x1) × [y0, y1) of a W-wide array of whole numbers: the mean is exact in any order; the
    /// squared deviations are summed pairwise, row after row, as numpy sums a fresh contiguous array.
    static func variance(_ a: [Double], _ W: Int, _ x0: Int, _ x1: Int, _ y0: Int, _ y1: Int) -> Double {
        let count = (x1 - x0) * (y1 - y0)
        var s = 0.0
        for y in y0..<y1 {
            for x in x0..<x1 { s += a[y * W + x] }
        }
        let mean = s / Double(count)
        var d = [Double](repeating: 0, count: count)
        var k = 0
        for y in y0..<y1 {
            for x in x0..<x1 {
                let v = a[y * W + x] - mean
                d[k] = v * v
                k += 1
            }
        }
        return pairwiseSum(d) / Double(count)
    }

    /// numpy's pairwise summation of a contiguous float64 array (8 accumulators, 128-element leaves).
    static func pairwiseSum(_ a: [Double]) -> Double {
        a.withUnsafeBufferPointer { pairwise($0, 0, $0.count) }
    }

    static func pairwise(_ a: UnsafeBufferPointer<Double>, _ lo: Int, _ n: Int) -> Double {
        if n < 8 {
            var res = 0.0
            for i in lo..<(lo + n) { res += a[i] }
            return res
        }
        if n <= 128 {
            var r0 = a[lo], r1 = a[lo + 1], r2 = a[lo + 2], r3 = a[lo + 3]
            var r4 = a[lo + 4], r5 = a[lo + 5], r6 = a[lo + 6], r7 = a[lo + 7]
            var i = 8
            while i < n - (n % 8) {
                r0 += a[lo + i]; r1 += a[lo + i + 1]; r2 += a[lo + i + 2]; r3 += a[lo + i + 3]
                r4 += a[lo + i + 4]; r5 += a[lo + i + 5]; r6 += a[lo + i + 6]; r7 += a[lo + i + 7]
                i += 8
            }
            var res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7))
            while i < n {
                res += a[lo + i]
                i += 1
            }
            return res
        }
        var n2 = n / 2
        n2 -= n2 % 8
        return pairwise(a, lo, n2) + pairwise(a, lo + n2, n - n2)
    }

    // MARK: imagehash.phash

    static let cos32: [[Double]] = (0..<32).map { k in (0..<32).map { i in 2 * cos(Double.pi * Double(k) * Double(2 * i + 1) / 64) } }

    /// imagehash.phash: Pillow's grey, Lanczos to 32×32, the DCT's 8×8 lowest frequencies against their median, as 16 hex
    /// digits (the first coefficient is the top bit).
    public static func phash(_ img: Picture) -> String {
        let small = Pillow.resample(Pillow.grey(img), 32, 32, .lanczos)
        let px = small.pixels.map(Double.init)
        var d = [Double](repeating: 0, count: 64)
        for u in 0..<8 {
            for v in 0..<8 {
                var s = 0.0
                for i in 0..<32 {
                    var row = 0.0
                    for j in 0..<32 { row += px[i * 32 + j] * cos32[v][j] }
                    s += cos32[u][i] * row
                }
                d[u * 8 + v] = s
            }
        }
        let sorted = d.sorted()
        let med = (sorted[31] + sorted[32]) / 2
        var bits: UInt64 = 0
        for x in d { bits = (bits << 1) | (x > med ? 1 : 0) }
        return String(format: "%016llx", bits)
    }

    /// How many of the 64 bits two perceptual hashes differ in (imagehash's `a - b`).
    public static func distance(_ a: String, _ b: String) -> Int {
        guard let x = UInt64(a, radix: 16), let y = UInt64(b, radix: 16) else { return 64 }
        return (x ^ y).nonzeroBitCount
    }
}
