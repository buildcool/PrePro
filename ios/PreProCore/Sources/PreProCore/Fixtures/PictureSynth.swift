import Foundation

/// Test photos both apps make to the same pixel (scripts/portable_picture.py): whole-number formulas and SplitMix64 noise
/// only, so the photo analysis is checked against the desktop's on identical pixels without committing image files. A
/// picture is a scene — a sky over land, rectangles and discs, fine noise, optionally faces — optionally out of focus
/// (a box blur), dimmed (a dark shot), or seen a few pixels to the side (a burst's second frame).
public enum PictureSynth {
    public struct Spec: Codable, Hashable, Sendable {
        public var w: Int
        public var h: Int
        public var seed: Int
        public var palette: String
        public var shapes: Int
        public var noise: Int
        public var dx: Int
        public var dy: Int
        public var blur: Int
        public var dim: [Int]?
        public var faces: [[Int]]                  // (x, y, width) in thousandths of the picture
    }

    static let golden: UInt64 = 0x9E37_79B9_7F4A_7C15
    static let mix1: UInt64 = 0xBF58_476D_1CE4_E5B9
    static let mix2: UInt64 = 0x94D0_49BB_1331_11EB
    static let noiseSeed: UInt64 = 0x5EED_F00D

    // (sky top, sky at the horizon, land at the horizon, land at the bottom)
    static let palettes: [String: [[Int]]] = [
        "beach": [[70, 140, 215], [175, 215, 240], [235, 210, 160], [200, 170, 120]],
        "cafe": [[120, 90, 70], [200, 170, 140], [150, 110, 80], [90, 60, 45]],
        "food": [[230, 225, 215], [245, 240, 230], [190, 120, 70], [140, 80, 50]],
        "market": [[90, 150, 210], [190, 210, 230], [180, 90, 60], [110, 70, 50]],
        "forest": [[60, 120, 90], [150, 190, 160], [60, 100, 50], [30, 60, 30]],
        "sunset": [[40, 40, 110], [250, 140, 70], [90, 60, 70], [30, 20, 30]],
        "city": [[40, 60, 100], [120, 140, 170], [90, 90, 95], [50, 50, 55]],
    ]
    static let skin = [222, 180, 145], eye = [40, 28, 20], mouth = [170, 80, 80]

    static func mix(_ z0: UInt64) -> UInt64 {
        var z = z0
        z = (z ^ (z >> 30)) &* mix1
        z = (z ^ (z >> 27)) &* mix2
        return z ^ (z >> 31)
    }

    /// SplitMix64 seeded with `seed`: its k-th output (k = 1, 2, …).
    static func stream(_ seed: UInt64, _ k: UInt64) -> UInt64 { mix(seed &+ k &* golden) }

    public static func picture(_ s: Spec) -> Picture {
        let w = s.w, h = s.h
        let pal = palettes[s.palette] ?? palettes["beach"]!
        let (top, sky, land, bottom) = (pal[0], pal[1], pal[2], pal[3])
        let hz = h * (55 + s.seed % 10) / 100                       // the horizon
        var img = [Int](repeating: 0, count: w * h * 3)
        let light = (0..<w).map { (($0 + s.dx) * 24) / w }          // a little light from the right
        for y in 0..<h {
            let Y = y + s.dy
            let ys = min(max(Y, 0), hz), yl = min(max(Y - hz, 0), h - hz)
            for c in 0..<3 {
                let base = Y < hz ? (top[c] * (hz - ys) + sky[c] * ys) / hz : (land[c] * (h - hz - yl) + bottom[c] * yl) / (h - hz)
                var i = y * w * 3 + c
                for x in 0..<w {
                    img[i] = base + light[x]
                    i += 3
                }
            }
        }
        func paint(_ x: Int, _ y: Int, _ rgb: [Int]) {
            let i = (y * w + x) * 3
            img[i] = rgb[0]
            img[i + 1] = rgb[1]
            img[i + 2] = rgb[2]
        }
        // in scene coordinates (X = x + dx, Y = y + dy): paint the part of [x0, x1] × [y0, y1] in view where `inside`
        func fill(_ x0: Int, _ x1: Int, _ y0: Int, _ y1: Int, _ rgb: [Int], _ inside: (Int, Int) -> Bool) {
            let xa = max(x0, s.dx), xb = min(x1, w - 1 + s.dx), ya = max(y0, s.dy), yb = min(y1, h - 1 + s.dy)
            guard xa <= xb, ya <= yb else { return }
            for Y in ya...yb {
                for X in xa...xb where inside(X, Y) { paint(X - s.dx, Y - s.dy, rgb) }
            }
        }
        let r = (0..<(6 * s.shapes)).map { stream(UInt64(s.seed), UInt64($0 + 1)) }
        for i in 0..<s.shapes {
            let kind = Int(r[6 * i] % 2), cx = Int(r[6 * i + 1] % UInt64(w)), cy = Int(r[6 * i + 2] % UInt64(h))
            let size = w / 20 + Int(r[6 * i + 3] % UInt64(w / 7)), col = Int(r[6 * i + 4] >> 40)
            let rgb = [(col >> 16) & 255, (col >> 8) & 255, col & 255]
            if kind == 0 {
                fill(cx - size, cx + size, cy - size * 2 / 3, cy + size * 2 / 3, rgb) { _, _ in true }
            } else {
                fill(cx - size, cx + size, cy - size, cy + size, rgb) { X, Y in (X - cx) * (X - cx) + (Y - cy) * (Y - cy) <= size * size }
            }
        }
        for f in s.faces {
            let cx = w * f[0] / 1000, cy = h * f[1] / 1000, a = w * f[2] / 2000
            let b = a * 13 / 10
            fill(cx - a, cx + a, cy - b, cy + b, skin) { X, Y in
                (X - cx) * (X - cx) * (b * b) + (Y - cy) * (Y - cy) * (a * a) <= (a * b) * (a * b)
            }
            let er = max(2, a / 7), ey = cy - b / 6
            for ex in [cx - a * 2 / 5, cx + a * 2 / 5] {
                fill(ex - er, ex + er, ey - er, ey + er, eye) { X, Y in (X - ex) * (X - ex) + (Y - ey) * (Y - ey) <= er * er }
            }
            let mr = max(1, b / 14), my = cy + b * 9 / 20, mw = a * 2 / 5
            fill(cx - mw, cx + mw, my - mr, my + mr, mouth) { _, _ in true }
        }
        if s.noise != 0 {
            let seed = noiseSeed ^ UInt64(s.seed), stride = w + 128
            for y in 0..<h {
                let row = (y + s.dy + 64) * stride
                for x in 0..<w {
                    let z = stream(seed, UInt64(row + x + s.dx + 64 + 1))   // the noise belongs to the scene too
                    let i = (y * w + x) * 3
                    img[i] += Int((z >> 60) & 15) * s.noise / 8 - s.noise
                    img[i + 1] += Int((z >> 52) & 15) * s.noise / 8 - s.noise
                    img[i + 2] += Int((z >> 44) & 15) * s.noise / 8 - s.noise
                }
            }
        }
        for i in 0..<img.count { img[i] = min(255, max(0, img[i])) }
        if s.blur > 0 {
            for _ in 0..<3 {
                img = box(img, w, h, s.blur, alongX: true)
                img = box(img, w, h, s.blur, alongX: false)
            }
        }
        if let d = s.dim, d.count == 2 {
            for i in 0..<img.count { img[i] = (img[i] * d[0] + d[1] / 2) / d[1] }
        }
        return Picture(width: w, height: h, pixels: img.map { UInt8($0) })
    }

    /// A box blur of radius r along x or y, the edge pixel repeated, rounded to the nearest level (halves up).
    static func box(_ a: [Int], _ w: Int, _ h: Int, _ r: Int, alongX: Bool) -> [Int] {
        let n = 2 * r + 1
        var out = [Int](repeating: 0, count: a.count)
        let lines = alongX ? h : w, len = alongX ? w : h
        let step = alongX ? 3 : 3 * w
        for line in 0..<lines {
            for c in 0..<3 {
                let start = (alongX ? line * w * 3 : line * 3) + c
                func at(_ i: Int) -> Int { a[start + min(max(i, 0), len - 1) * step] }
                var sum = 0
                for i in -r...r { sum += at(i) }
                for i in 0..<len {
                    out[start + i * step] = (sum + n / 2) / n
                    sum += at(i + r + 1) - at(i - r)
                }
            }
        }
        return out
    }
}
