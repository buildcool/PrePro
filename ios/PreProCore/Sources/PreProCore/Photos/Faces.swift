import CoreGraphics
import Foundation
import Vision

/// Faces in a photo, found on the phone with Apple's Vision, reported the way the desktop's detector reports them
/// (analyze/visual.py FaceDetector): centre, width and height as fractions of the picture with y running down,
/// confidence ≥ 0.6, none narrower or shorter than 3 % of the picture, the surest first.
public enum Faces {
    public static func find(in img: PhotoPixels, minConfidence: Double = 0.6) -> [FaceBox] {
        guard let cg = img.cgImage else { return [] }
        let request = VNDetectFaceRectanglesRequest()
        let handler = VNImageRequestHandler(cgImage: cg, orientation: .up, options: [:])
        do {
            try handler.perform([request])
        } catch {
            return []
        }
        var out: [FaceBox] = []
        for o in request.results ?? [] {
            let conf = Double(o.confidence)
            guard conf >= minConfidence else { continue }
            let r = o.boundingBox                                  // normalised, origin at the bottom left
            let x0 = max(0, Double(r.minX)), x1 = min(1, Double(r.maxX))
            let y0 = max(0, 1 - Double(r.maxY)), y1 = min(1, 1 - Double(r.minY))
            guard x1 - x0 >= 0.03, y1 - y0 >= 0.03 else { continue }
            out.append(FaceBox(t: 0, x: (x0 + x1) / 2, y: (y0 + y1) / 2, w: x1 - x0, h: y1 - y0, conf: Py.round(conf, 3)))
        }
        return out.stableSorted { a, b in a.conf != b.conf ? a.conf > b.conf : a.w * a.h > b.w * b.h }
    }
}

extension PhotoPixels {
    /// An image drawn into 8-bit RGB (sRGB): a video frame, a preview.
    public init?(cgImage cg: CGImage) {
        let w = cg.width, h = cg.height
        guard w > 0, h > 0, let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        var rgbx = [UInt8](repeating: 0, count: w * h * 4)
        let ok = rgbx.withUnsafeMutableBytes { raw -> Bool in
            guard let ctx = CGContext(data: raw.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: space,
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return false }
            ctx.interpolationQuality = .none
            ctx.setBlendMode(.copy)
            ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        guard ok else { return nil }
        self = rgbx.withUnsafeBufferPointer { Pillow.upright($0, width: w, height: h, stride: 4, orientation: 1) }
    }

    /// The picture as a CGImage (8-bit RGB or grey, sRGB), for Vision and for drawing.
    public var cgImage: CGImage? {
        let rgb = channels == 3
        guard let space = rgb ? CGColorSpace(name: CGColorSpace.sRGB) : CGColorSpace(name: CGColorSpace.linearGray),
              let provider = CGDataProvider(data: Data(pixels) as CFData) else { return nil }
        return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 8 * channels, bytesPerRow: width * channels,
                       space: space, bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue), provider: provider,
                       decode: nil, shouldInterpolate: false, intent: .defaultIntent)
    }
}
