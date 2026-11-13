import Foundation

/// An 8-bit picture held the way Pillow holds one after convert("RGB") or convert("L"): rows top to bottom, each
/// pixel's channels side by side.
public struct Picture: Equatable, Sendable {
    public var width: Int
    public var height: Int
    public var channels: Int                   // 3 (RGB) or 1 (grey)
    public var pixels: [UInt8]

    public init(width: Int, height: Int, channels: Int = 3, pixels: [UInt8]) {
        precondition(pixels.count == width * height * channels, "a \(width)×\(height)×\(channels) picture")
        self.width = width
        self.height = height
        self.channels = channels
        self.pixels = pixels
    }

    /// FNV-1a (64 bit) of the pixel bytes: a picture's fingerprint in the golden files (portable_picture.fnv).
    public var fingerprint: String {
        var h: UInt64 = 0xCBF2_9CE4_8422_2325
        pixels.withUnsafeBufferPointer { p in
            for b in p { h = (h ^ UInt64(b)) &* 0x0000_0100_0000_01B3 }
        }
        return String(format: "%016llx", h)
    }
}

/// Pillow's own resizing, to the last bit (libImaging Reduce.c and Resample.c, 8 bits per channel), and its EXIF turn:
/// the iPhone makes the very thumbnail the desktop measures a photo on (`Image.thumbnail((480, 480))` of the upright
/// photo: a box reduction by a whole factor, then bicubic).
enum Pillow {
    static let precisionBits = 32 - 8 - 2

    // MARK: EXIF orientation (ImageOps.exif_transpose)

    /// The picture turned upright: `pixels` stored under EXIF `orientation` (1…8), `stride` bytes a pixel, of which the
    /// first three are R, G, B (or one grey byte when stride is 1).
    static func upright(_ src: UnsafeBufferPointer<UInt8>, width W: Int, height H: Int, stride: Int, orientation: Int) -> Picture {
        let swap = orientation >= 5 && orientation <= 8
        let w = swap ? H : W, h = swap ? W : H
        let C = stride >= 3 ? 3 : 1
        // where pixel (x, y) of the upright picture is stored: base + x·sx + y·sy (in pixels)
        let walk: (Int, Int, Int) = switch orientation {
        case 2: (W - 1, -1, W)                                        // FLIP_LEFT_RIGHT
        case 3: ((H - 1) * W + W - 1, -1, -W)                         // ROTATE_180
        case 4: ((H - 1) * W, 1, -W)                                  // FLIP_TOP_BOTTOM
        case 5: (0, W, 1)                                             // TRANSPOSE: (x, y) ← (y, x)
        case 6: ((H - 1) * W, -W, 1)                                  // ROTATE_270: (x, y) ← (y, H−1−x)
        case 7: ((H - 1) * W + W - 1, -W, -1)                         // TRANSVERSE: (x, y) ← (W−1−y, H−1−x)
        case 8: (W - 1, W, -1)                                        // ROTATE_90: (x, y) ← (W−1−y, x)
        default: (0, 1, W)
        }
        let (base, sx, sy) = walk
        var out = [UInt8](repeating: 0, count: w * h * C)
        out.withUnsafeMutableBufferPointer { dst in
            var o = 0
            for y in 0..<h {
                var p = base + y * sy
                for _ in 0..<w {
                    let i = p * stride
                    for c in 0..<C { dst[o + c] = src[i + c] }
                    o += C
                    p += sx
                }
            }
        }
        return Picture(width: w, height: h, channels: C, pixels: out)
    }

    static func upright(_ img: Picture, orientation: Int) -> Picture {
        img.pixels.withUnsafeBufferPointer {
            upright($0, width: img.width, height: img.height, stride: img.channels, orientation: orientation)
        }
    }

    // MARK: Image.reduce (Reduce.c)

    static func division(_ divider: Int, _ resultBits: Int) -> UInt64 {
        UInt64(Float(4_294_967_296.0) / Float((1 << resultBits) * divider))
    }

    /// Image.reduce((fx, fy)) of the whole picture: box averages; the last column and row average what is left.
    static func reduce(_ img: Picture, _ fx: Int, _ fy: Int) -> Picture {
        let W = img.width, H = img.height, C = img.channels
        let ow = (W + fx - 1) / fx, oh = (H + fy - 1) / fy
        let fullW = W / fx, fullH = H / fy
        var out = [UInt8](repeating: 0, count: ow * oh * C)
        img.pixels.withUnsafeBufferPointer { src in
            out.withUnsafeMutableBufferPointer { dst in
                // one output pixel from the source block [x0, x1) × [y0, y1)
                func block(_ x0: Int, _ x1: Int, _ y0: Int, _ y1: Int, _ m: UInt64, _ amend: UInt64, into o: Int) {
                    for c in 0..<C {
                        var ss = amend
                        for y in y0..<y1 {
                            var i = (y * W + x0) * C + c
                            for _ in x0..<x1 {
                                ss += UInt64(src[i])
                                i += C
                            }
                        }
                        dst[o + c] = UInt8(truncatingIfNeeded: (ss * m) >> 24)
                    }
                }
                let mFull = division(fx * fy, 8), aFull = UInt64(fx * fy / 2)
                for y in 0..<fullH {
                    for x in 0..<fullW {
                        block(x * fx, x * fx + fx, y * fy, y * fy + fy, mFull, aFull, into: (y * ow + x) * C)
                    }
                }
                if W % fx != 0 {                                          // the last column
                    let scale = (W % fx) * fy
                    let m = division(scale, 8), a = UInt64(scale / 2)
                    for y in 0..<fullH { block(fullW * fx, W, y * fy, y * fy + fy, m, a, into: (y * ow + fullW) * C) }
                }
                if H % fy != 0 {                                          // the last row
                    let scale = (H % fy) * fx
                    let m = division(scale, 8), a = UInt64(scale / 2)
                    for x in 0..<fullW { block(x * fx, x * fx + fx, fullH * fy, H, m, a, into: (fullH * ow + x) * C) }
                }
                if W % fx != 0 && H % fy != 0 {                           // the corner
                    let scale = (W % fx) * (H % fy)
                    block(fullW * fx, W, fullH * fy, H, division(scale, 8), UInt64(scale / 2), into: (fullH * ow + fullW) * C)
                }
            }
        }
        return Picture(width: ow, height: oh, channels: C, pixels: out)
    }

    // MARK: Image.resize (Resample.c)

    enum Filter {
        case bicubic, lanczos

        var support: Double { self == .bicubic ? 2.0 : 3.0 }

        func callAsFunction(_ x0: Double) -> Double {
            switch self {
            case .bicubic:
                let a = -0.5
                let x = x0 < 0 ? -x0 : x0
                if x < 1.0 { return ((a + 2.0) * x - (a + 3.0)) * x * x + 1 }
                if x < 2.0 { return (((x - 5) * x + 8) * x - 4) * a }
                return 0.0
            case .lanczos:
                func sinc(_ v: Double) -> Double {
                    if v == 0.0 { return 1.0 }
                    let t = v * Double.pi
                    return sin(t) / t
                }
                return (-3.0 <= x0 && x0 < 3.0) ? sinc(x0) * sinc(x0 / 3) : 0.0
            }
        }
    }

    /// precompute_coeffs + normalize_coeffs_8bpc: for each output pixel, the first input pixel it reads, how many, and
    /// their weights in fixed point.
    static func coefficients(inSize: Int, in0: Float, in1: Float, outSize: Int, filter: Filter) -> (bounds: [(Int, Int)], k: [[Int]]) {
        let scale = Double(in1 - in0) / Double(outSize)
        let filterscale = scale < 1.0 ? 1.0 : scale
        let support = filter.support * filterscale
        let one = Double(1 << precisionBits)
        var bounds: [(Int, Int)] = []
        var kk: [[Int]] = []
        bounds.reserveCapacity(outSize)
        kk.reserveCapacity(outSize)
        for xx in 0..<outSize {
            let center = Double(in0) + (Double(xx) + 0.5) * scale
            let ss = 1.0 / filterscale
            var xmin = Int(center - support + 0.5)
            if xmin < 0 { xmin = 0 }
            var xmax = Int(center + support + 0.5)
            if xmax > inSize { xmax = inSize }
            xmax -= xmin
            var k = [Double](repeating: 0, count: max(0, xmax))
            var ww = 0.0
            for x in 0..<max(0, xmax) {
                let w = filter((Double(x + xmin) - center + 0.5) * ss)
                k[x] = w
                ww += w
            }
            if ww != 0.0 {
                for x in 0..<k.count { k[x] /= ww }
            }
            kk.append(k.map { $0 < 0 ? Int(-0.5 + $0 * one) : Int(0.5 + $0 * one) })
            bounds.append((xmin, max(0, xmax)))
        }
        return (bounds, kk)
    }

    static func clip8(_ v: Int) -> UInt8 {
        if v >= (1 << (precisionBits + 8)) { return 255 }
        if v <= 0 { return 0 }
        return UInt8(v >> precisionBits)
    }

    /// ImagingResample with a box (Pillow's `box` in floats): the horizontal pass over just the rows the vertical pass
    /// reads, then the vertical pass.
    static func resample(_ img: Picture, _ outW: Int, _ outH: Int, _ filter: Filter, box: (Float, Float, Float, Float)? = nil) -> Picture {
        let W = img.width, H = img.height, C = img.channels
        let b = box ?? (0, 0, Float(W), Float(H))
        let needH = outW != W || b.0 != 0 || b.2 != Float(outW)
        let needV = outH != H || b.1 != 0 || b.3 != Float(outH)
        let (bh, kh) = coefficients(inSize: W, in0: b.0, in1: b.2, outSize: outW, filter: filter)
        var (bv, kv) = coefficients(inSize: H, in0: b.1, in1: b.3, outSize: outH, filter: filter)
        let yFirst = bv[0].0
        let yLast = bv[outH - 1].0 + bv[outH - 1].1
        var cur = img
        let half = 1 << (precisionBits - 1)
        if needH {
            bv = bv.map { ($0.0 - yFirst, $0.1) }
            let rows = yLast - yFirst
            var tmp = [UInt8](repeating: 0, count: rows * outW * C)
            img.pixels.withUnsafeBufferPointer { src in
                tmp.withUnsafeMutableBufferPointer { dst in
                    for yy in 0..<rows {
                        let row = (yy + yFirst) * W * C
                        for xx in 0..<outW {
                            let (xmin, xmax) = bh[xx]
                            let k = kh[xx]
                            for c in 0..<C {
                                var ss = half
                                var i = row + xmin * C + c
                                for x in 0..<xmax {
                                    ss += Int(src[i]) * k[x]
                                    i += C
                                }
                                dst[(yy * outW + xx) * C + c] = clip8(ss)
                            }
                        }
                    }
                }
            }
            cur = Picture(width: outW, height: rows, channels: C, pixels: tmp)
        }
        guard needV else { return cur }
        let w = cur.width
        var out = [UInt8](repeating: 0, count: outH * w * C)
        cur.pixels.withUnsafeBufferPointer { src in
            out.withUnsafeMutableBufferPointer { dst in
                for yy in 0..<outH {
                    let (ymin, ymax) = bv[yy]
                    let k = kv[yy]
                    for xx in 0..<w {
                        for c in 0..<C {
                            var ss = half
                            var i = (ymin * w + xx) * C + c
                            for y in 0..<ymax {
                                ss += Int(src[i]) * k[y]
                                i += w * C
                            }
                            dst[(yy * w + xx) * C + c] = clip8(ss)
                        }
                    }
                }
            }
        }
        return Picture(width: w, height: outH, channels: C, pixels: out)
    }

    // MARK: Image.thumbnail

    /// The size Image.thumbnail((maxW, maxH)) gives (None when the picture already fits).
    static func thumbnailSize(_ W: Int, _ H: Int, _ maxW: Int = 480, _ maxH: Int = 480) -> (Int, Int)? {
        if maxW >= W && maxH >= H { return nil }
        let aspect = Double(W) / Double(H)
        // max(min(floor, ceil, key=key), 1): the first of the two on a tie
        func roundAspect(_ number: Double, _ key: (Int) -> Double) -> Int {
            let lo = Int(number.rounded(.down)), hi = Int(number.rounded(.up))
            return max(key(hi) < key(lo) ? hi : lo, 1)
        }
        var x = maxW, y = maxH
        if Double(x) / Double(y) >= aspect {
            x = roundAspect(Double(y) * aspect) { abs(aspect - Double($0) / Double(maxH)) }
        } else {
            y = roundAspect(Double(x) / aspect) { $0 == 0 ? 0 : abs(aspect - Double(maxW) / Double($0)) }
        }
        return (x, y)
    }

    /// Image.thumbnail((maxSide, maxSide)) with its defaults (bicubic, reducing_gap 2.0) on a decoded picture.
    static func thumbnail(_ img: Picture, maxSide: Int = 480, reducingGap: Double = 2.0) -> Picture {
        guard let size = thumbnailSize(img.width, img.height, maxSide, maxSide) else { return img }
        let (ow, oh) = size
        var src = img
        var box: (Float, Float, Float, Float) = (0, 0, Float(img.width), Float(img.height))
        let fx = max(1, Int(Double(img.width) / Double(ow) / reducingGap))
        let fy = max(1, Int(Double(img.height) / Double(oh) / reducingGap))
        if fx > 1 || fy > 1 {
            src = reduce(img, fx, fy)
            box = (0, 0, Float(Double(img.width) / Double(fx)), Float(Double(img.height) / Double(fy)))
        }
        return resample(src, ow, oh, .bicubic, box: box)
    }

    // MARK: grey

    /// Pillow's convert("L").
    static func grey(_ img: Picture) -> Picture {
        guard img.channels == 3 else { return img }
        var out = [UInt8](repeating: 0, count: img.width * img.height)
        img.pixels.withUnsafeBufferPointer { p in
            for i in 0..<out.count {
                let r = UInt32(p[3 * i]), g = UInt32(p[3 * i + 1]), b = UInt32(p[3 * i + 2])
                out[i] = UInt8((r * 19595 + g * 38470 + b * 7471 + 0x8000) >> 16)
            }
        }
        return Picture(width: img.width, height: img.height, channels: 1, pixels: out)
    }
}
