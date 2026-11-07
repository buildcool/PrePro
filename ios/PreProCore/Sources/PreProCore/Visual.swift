import Foundation

/// Framing facts about a picture — the decision-side parts of the desktop's src/prepro/analyze/visual.py.
public enum Visual {
    /// Whether a photo can fill a frame of aspect `outAspect` (width / height) without cutting anyone out: not a group
    /// photo whose faces spread wider than the crop window, and not a panorama of which a filled frame would show
    /// under a third.
    public static func photoFills(_ displaySize: (w: Int, h: Int)?, faces: [FaceBox], outAspect: Double) -> Bool {
        guard let ds = displaySize, ds.h != 0, ds.w != 0 else { return true }
        let cropW = outAspect / (Double(ds.w) / Double(ds.h))
        var span = 0.0
        if faces.count >= 2, let right = faces.map({ $0.x + $0.w / 2 }).max(), let left = faces.map({ $0.x - $0.w / 2 }).min() {
            span = right - left
        }
        return !(span > 0.92 * min(1.0, cropW) || cropW < 0.3)
    }
}
