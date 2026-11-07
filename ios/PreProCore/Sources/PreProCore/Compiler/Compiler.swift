import Foundation

/// Story + polish → the frame-exact timeline the phone previews and renders — a port of the desktop's
/// src/prepro/timeline/compiler.py, format by format (photo reels first). Everything placed by a decision carries a
/// suggestion with its reason, so the creator can keep or reject it in the review.
public enum Compiler {
    public static let sizes: [String: (w: Int, h: Int)] = ["9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)]
    static let musicWords = ["front": "up front", "bed": "under the talking", "light": "softly, under the clips' own sound"]
    static let appliedConf = 0.5

    public static func compile(_ pa: ProjectAnalysis, direction d: Direction, story: StoryPlan, polish: PolishPlan,
                               brief: CreatorBrief = .empty, fps: Double = 30) throws -> Timeline {
        guard d.playbook == "photo_reel" else { throw BrainError.notOnPhoneYet(d.playbook) }
        let size = sizes[d.aspect] ?? (1920, 1080)
        let ctx = CompileContext(pa: pa, d: d, story: story, polish: polish, brief: brief, W: size.w, H: size.h, fps: fps)
        let no = Set(brief.rules.filter { $0.kind == "no_effect" }.map(\.target))
        let pb = try Knowledge.playbook(d.playbook)
        let brollLen = Py.number(d.knobs.shotLen) ?? Py.mean(pb.pacing.brollShot)
        let used = Set(story.items.map(\.ref))

        // ---- what was left out, each with its reason (and a way back in the review)
        for a in pa.assets where a.kind == "broll" {
            for sh in pa.clips[a.id]?.shots ?? [] where !used.contains(sh.id) {
                let bad = Set(sh.flags).intersection(["dark", "blurry", "shaky", "pocket"])
                if !bad.isEmpty {
                    ctx.suggest("cut", "Left out \(a.name) — \(bad.sorted(by: Py.less).joined(separator: ", "))", conf: 0.8,
                                payload: ["asset": .string(a.id), "shot": .string(sh.id), "key": .string("shot:\(sh.id)")])
                } else if Py.text(sh.dupGroup) != nil && sh.dupRank > 0 {
                    ctx.suggest("cut", "Left out \(a.name) — near-duplicate of a better take", conf: 0.75,
                                payload: ["asset": .string(a.id), "shot": .string(sh.id), "key": .string("shot:\(sh.id)")])
                }
            }
        }
        for a in pa.assets where a.kind == "image" {                 // every photo left out says why, and can come back
            guard let sh = pa.clips[a.id]?.shots.first, !used.contains(sh.id) else { continue }
            let bad = Set(sh.flags).intersection(["dark", "blurry"]).sorted(by: Py.less)
            let why = !bad.isEmpty ? bad.joined(separator: ", ")
                : (Py.text(sh.dupGroup) != nil && sh.dupRank > 0 ? "a burst shot — the sharpest of the burst is in"
                    : "to keep the reel tight — the least striking photos go first")
            ctx.suggest("cut", "Left out \(a.name) — \(why)", conf: 0.75,
                        payload: ["asset": .string(a.id), "shot": .string(sh.id), "key": .string("shot:\(sh.id)")])
        }

        // ---- each photo holds whole beats of the song (the story says how many), laid on the song's beat grid here, so
        // dropping or adding a photo in the review keeps every cut on the beat; a photo holds long enough to read its line
        var reelBeats: [Double]?
        var lineOn: [Int: String] = [:]
        if story.items.contains(where: { ($0.beats ?? 0) != 0 }) {
            if let cue = polish.music.first(where: { Py.text($0.trackId) != nil && $0.offset != nil && $0.mode != "none" }),
               let track = cue.trackId, let offset = cue.offset, let mi = pa.clips[track]?.music, mi.beats.count > 8 {
                reelBeats = mi.beats.filter { $0 >= offset - 1e-3 }.map { Py.round($0 - offset, 4) }
            }
            for c in polish.effects where c.type == "text" && Py.text(c.text) != nil && c.at.hasPrefix("photo:") && c.style == "photo" && c.intent == "brief" {
                if let k = Int(c.at.dropFirst("photo:".count)) { lineOn[k] = c.text }
            }
        }
        var nReel = 0
        var t = 0.0
        for it in story.items {
            let sec = it.section
            if ctx.sectionT[sec] == nil { ctx.sectionT[sec] = [t, t] }
            guard let shot = pa.shot(it.ref) else {
                if pa.clips.values.contains(where: { $0.transcript?.segments.contains { $0.id == it.ref } ?? false }) {
                    throw BrainError.notOnPhoneYet("talking clips")
                }
                continue
            }
            guard let asset = pa.asset(shot.assetId), asset.kind == "image" || asset.info.isImage || asset.kind == "meme_image" else {
                throw BrainError.notOnPhoneYet("video clips")
            }
            let a = it.t0 ?? shot.t0
            var b = it.t1 ?? min(shot.t1, a + brollLen)
            if (it.beats ?? 0) != 0 && asset.kind == "image" {
                let line = it.role != "loop" ? lineOn[nReel] : nil
                let need = line.map { 0.75 + Double(Py.words($0).count) / 3.0 } ?? 0.0
                b = a + beatLength(reelBeats, at: t, beats: it.beats ?? 0, need: need, fallback: max(b - a, 0.6))
                if it.role != "loop" { nReel += 1 }
            }
            var v = Item(id: ctx.iid("v"), ref: it.ref, track: "V1", kind: "image", assetId: asset.id, recIn: t, duration: b - a,
                         role: it.role, section: sec)
            if asset.kind == "image" {                                // photos move like a camera, never freeze ("no zooms": framed, still)
                let still = no.contains("zoom") || !d.knobs.photoMotion
                v.transform = photoMotion(ctx, shot, dur: still ? 0.0 : b - a, index: ctx.nPhotos)
                if let tf = v.transform, !tf.keys.isEmpty { v.note = "kenburns" }
                ctx.nPhotos += 1
            }
            ctx.items.append(v)
            ctx.spans[it.ref, default: []].append((t, t + v.recDur))
            t += v.recDur
            if it.role == "loop" {
                ctx.suggest("loop", Py.text(it.note) ?? "loop ending", conf: 0.75, t: v.recIn, items: [v.id],
                            payload: ["key": .string("loop:\(it.ref)"), "ref": .string(it.ref)])
            }
            if it.role == "hook" || it.role == "establishing" {
                // a photo reel's cover: rejecting it opens on the next best photo instead
                let key = it.role == "hook" ? ((it.beats ?? 0) != 0 ? "cover:\(it.ref)" : "hook") : "item:\(it.ref)"
                ctx.suggest(it.role == "hook" ? "hook" : "broll", Py.text(it.note) ?? it.role, conf: 0.85, t: v.recIn, items: [v.id],
                            payload: ["key": .string(key), "ref": .string(it.ref)])
            }
            ctx.sectionT[sec]?[1] = t
        }
        let total = t

        seamlessLoop(ctx)
        let moving = ctx.items.filter { $0.track == "V1" && $0.note == "kenburns" }
        if let first = moving.first {                               // one decision for the whole reel: rejecting it frames every photo still
            ctx.suggest("motion", "Photos move like a camera: a slow push-in, pull-out or drift on each, never a frozen still",
                        conf: 0.8, t: first.recIn, items: moving.map(\.id), payload: ["key": .string("photomotion")])
        }

        // ---- words (T1)
        let faceAt = faceLookup(ctx)
        var stamps: [Item] = []
        for c in polish.effects where c.type == "text" {
            guard let text = Py.text(c.text) else { continue }
            var dur = Py.number(c.dur) ?? 2.4
            let t0: Double
            if c.at == "start" {
                t0 = 0.05
            } else if c.at == "end" {
                t0 = max(0.0, total - dur - 0.1)
            } else if c.at.hasPrefix("section:") {
                guard let s = ctx.sectionT[String(c.at.dropFirst("section:".count))] else { continue }
                t0 = s[0] + 0.25
            } else if let span = ctx.spans[c.at]?.first {
                t0 = span.0
                if c.dur == nil { dur = max(span.1 - span.0 - 0.03, c.style == "stamp" ? 1.3 : 0.8) }
            } else if c.at.hasPrefix("t:") {                          // an exact time (photo reels: lines land on the beat grid)
                guard let v = Double(c.at.dropFirst(2)) else { continue }
                t0 = v
            } else if c.at.hasPrefix("clip:") {
                let clips = ctx.items.filter { $0.track == "V1" }.stableSorted { $0.recIn < $1.recIn }
                guard let k = Int(c.at.dropFirst("clip:".count)), k < clips.count else { continue }
                t0 = clips[k].recIn
            } else if c.at.hasPrefix("photo:") {                      // the i-th photo (0 = the cover), for as long as it is up
                let pics = ctx.items.filter { $0.track == "V1" && $0.kind == "image" && $0.role != "loop" }.stableSorted { $0.recIn < $1.recIn }
                guard let k = Int(c.at.dropFirst("photo:".count)), k < pics.count else { continue }
                t0 = pics[k].recIn
                dur = Py.number(c.dur) ?? max(0.8, pics[k].recDur - 0.05)
            } else {
                continue
            }
            dur = min(dur, max(0.8, total - t0))
            let key = "fx:text:\(c.at)|\(Py.prefix(text, 24))"
            var pos = c.position
            var textY: Double?
            var textScale: Double?
            if (pos == "center" || pos == "upper") && c.style == "photo" {
                // the face wherever it goes while the words are up (a push-in grows it): clear of both ends of the move
                let ends = [faceAt(t0 + 0.05), faceAt(t0 + dur - 0.05)].compactMap { $0 }
                var fb: FaceBox4?
                if let e0 = ends.first {
                    let top = ends.map { $0.y - $0.h / 2 }.min()!, bot = ends.map { $0.y + $0.h / 2 }.max()!
                    fb = FaceBox4(x: e0.x, y: (top + bot) / 2, w: ends.map(\.w).max()!, h: bot - top)
                }
                let placed = besideFace(ctx, fb, text: text, pos: pos ?? "center")
                pos = placed.pos
                textY = placed.y
                textScale = placed.scale < 0.999 ? placed.scale : nil
            } else if pos == "center" {                               // never across a face: above or below it instead
                if let fb = faceAt(t0 + 0.2), fb.y - fb.h / 2 < 0.54 && fb.y + fb.h / 2 > 0.38 {
                    pos = fb.y > 0.46 ? "upper" : "lower"
                }
            } else if c.style == "stamp" {                            // a time stamp sits up top, unless a face is there
                if let fb = faceAt(t0 + 0.2), fb.y - fb.h / 2 < 0.24 { pos = "lower" }
            }
            let txt = Item(id: ctx.iid("t"), ref: key, track: "T1", kind: "text", recIn: Py.round(t0, 3), text: text, style: Py.text(c.style) ?? "title",
                           position: pos, textY: textY, textScale: textScale, duration: Py.round(dur, 3), role: "text")
            if c.intent == "stamp" && c.confidence >= appliedConf {
                ctx.items.append(txt)                                  // one decision for all of them, below
                stamps.append(txt)
                continue
            }
            if c.confidence < appliedConf {
                ctx.suggest("text", "\(c.why): “\(text)”", conf: c.confidence, t: t0, status: "optional",
                            payload: ["key": .string(key), "acceptable": .bool(true)])
            } else {
                ctx.items.append(txt)
                ctx.suggest("text", "\(c.why): “\(text)”", source: c.intent == "user" ? "user" : (c.confidence >= 1.0 ? "brief" : "rules"),
                            conf: c.confidence, t: t0, items: [txt.id], payload: ["key": .string(key)])
            }
        }
        if let first = stamps.first, let last = stamps.last {      // turning them down in the review removes every one
            ctx.suggest("text", "Time stamps from when you shot each moment (\(first.text ?? "") … \(last.text ?? "")), whenever the day moves on",
                        conf: 0.8, t: first.recIn, items: stamps.map(\.id), payload: ["key": .string("stamps")])
        }

        // ---- music (A2)
        try layMusic(ctx, total: total)

        let items = ctx.items.stableSorted { $0.recIn != $1.recIn ? $0.recIn < $1.recIn : Py.less($0.track, $1.track) }
        var meta: [String: JSONValue] = [:]
        meta["target"] = d.knobs.targetLength.map(JSONValue.number) ?? JSONValue.null
        meta["hook"] = d.hooks.first.map { JSONValue.of($0) } ?? JSONValue.null
        meta["story_why"] = JSONValue.string(story.why)
        meta["vo_script"] = JSONValue.of(polish.voScript)
        meta["broll_gaps"] = JSONValue.of(polish.brollGaps)
        meta["music"] = JSONValue.of(polish.music)
        meta["word_t"] = JSONValue.object([:])
        return Timeline(id: "\(d.id)-\(d.playbook)", name: d.name, directionId: d.id, playbook: d.playbook, fps: fps, width: size.w,
                        height: size.h, items: items, captions: [], markers: ctx.markers, suggestions: ctx.sugg,
                        musicSpans: ctx.musicSpans, look: polish.look, meta: meta)
    }

    // MARK: photos

    /// A still that moves like a camera (Ken Burns), never a frozen frame: a wide photo in a narrow frame pans gently
    /// onto its subject; otherwise a slow push-in (or pull-out, alternating so it never feels mechanical) on the face or
    /// the centre. Holds under 0.7 s stay still — motion that fast reads as jitter. A group photo whose faces don't all
    /// fit a filled frame (or a panorama) is shown whole on a blurred copy of itself: never cut a person out of a group.
    static func photoMotion(_ ctx: CompileContext, _ shot: Shot, dur: Double, index idx: Int) -> Transform? {
        let ds = ctx.pa.asset(shot.assetId)?.info.displaySize ?? (ctx.W, ctx.H)
        let srcAr = Double(ds.w) / Double(ds.h), outAr = Double(ctx.W) / Double(ctx.H)
        let face = shot.faces.max(by: { $0.w * $0.h < $1.w * $1.h })
        let fx = face?.x ?? 0.5, fy = face?.y ?? 0.45
        let cropW = outAr / srcAr
        if !Visual.photoFills(ds, faces: shot.faces, outAspect: outAr) {
            if dur < 0.7 { return Transform(fit: true) }
            let (z0, z1) = idx % 2 == 0 ? (1.0, 1.04) : (1.04, 1.0)
            return Transform(zoom: z0, keys: [TransformKey(t: 0.0, zoom: z0), TransformKey(t: Py.round(dur, 3), zoom: z1)], fit: true)
        }
        if dur < 0.7 {                                             // framed like the others, just not moving
            return Transform(cx: cropW < 1 ? Py.round(min(max(fx, cropW / 2), 1 - cropW / 2), 4) : 0.5, cy: cropW < 1 ? 0.5 : Py.round(fy, 4))
        }
        if cropW < 0.75 {                                          // much wider than the frame: pan across, ending on the subject
            let lo = cropW / 2, hi = 1 - cropW / 2
            let end = min(max(fx, lo), hi)
            // a drift, not a sweep: about 6 % of the frame's width a second, like the push-ins
            let span = min(0.06 * cropW * dur, 0.08, (hi - lo) / 2) * (idx % 2 == 1 ? 1 : -1)
            var start = min(max(end - span, lo), hi)
            if abs(end - start) < 0.01 { start = min(max(end + span, lo), hi) }
            let s = Py.round(start, 4)
            return Transform(cx: s, cy: 0.5, zoom: 1.0, keys: [TransformKey(t: 0.0, cx: s, cy: 0.5, zoom: 1.0),
                                                                TransformKey(t: Py.round(dur, 3), cx: Py.round(end, 4), cy: 0.5, zoom: 1.0)])
        }
        let (z0, z1) = idx % 2 == 0 ? (1.0, 1.07) : (1.07, 1.0)
        let cx = Py.round(min(max(fx, 0.35), 0.65), 4), cy = Py.round(min(max(fy, 0.35), 0.6), 4)
        return Transform(cx: cx, cy: cy, zoom: z0, keys: [TransformKey(t: 0.0, cx: cx, cy: cy, zoom: z0), TransformKey(t: Py.round(dur, 3), cx: cx, cy: cy, zoom: z1)])
    }

    /// How long a photo that starts at timeline time t holds for n beats of the reel's grid (beats counted from the
    /// song's start in the cut), stretched beat by beat until a line on it can be read; past the analysed beats the grid
    /// carries on at the song's tempo. No grid (the music was turned off): the planned length.
    static func beatLength(_ grid: [Double]?, at t: Double, beats n: Int, need: Double, fallback: Double) -> Double {
        guard let grid, grid.count >= 2, let lastBeat = grid.last else { return max(fallback, need) }
        let period = Py.median(Py.diff(Array(grid.prefix(64))))
        func at(_ k: Int) -> Double { k < grid.count ? grid[k] : lastBeat + Double(k - grid.count + 1) * period }
        let j: Int
        if t <= lastBeat {
            let dist = grid.map { abs($0 - t) }
            j = dist.indices.min(by: { dist[$0] < dist[$1] }) ?? 0
        } else {
            j = grid.count - 1 + Int(((t - lastBeat) / period).rounded(.toNearestOrEven))
        }
        var m = max(1, n)
        while at(j + m) - t < need && m < n + 32 { m += 1 }
        return Py.round(at(j + m) - t, 3)
    }

    /// A Reel that ends on its cover replays without a seam: the closing clip carries the cover's own move at the same
    /// speed and stops exactly on the cover's first frame. A push-in can't be continued backwards (it would zoom out past
    /// the whole photo), so the cover pulls out instead.
    static func seamlessLoop(_ ctx: CompileContext) {
        guard let li = ctx.items.firstIndex(where: { $0.track == "V1" && $0.role == "loop" }),
              let ci = ctx.items.firstIndex(where: { $0.track == "V1" && $0.role == "hook" && $0.assetId == ctx.items[li].assetId }),
              var cover = ctx.items[ci].transform, cover.keys.count >= 2 else { return }
        var k0 = cover.keys[0], k1 = cover.keys[cover.keys.count - 1]
        if k1.zoom > k0.zoom + 1e-3 {
            let z0 = k0.zoom, z1 = k1.zoom
            k0.zoom = z1
            k1.zoom = z0
            cover.cx = k0.cx
            cover.cy = k0.cy
            cover.zoom = k0.zoom
            cover.keys = [k0, k1]
            ctx.items[ci].transform = cover
        }
        let loopDur = ctx.items[li].recDur
        let f = loopDur / max(k1.t - k0.t, 1e-3)
        let start = TransformKey(t: 0.0, cx: Py.round(k0.cx - (k1.cx - k0.cx) * f, 4), cy: Py.round(k0.cy - (k1.cy - k0.cy) * f, 4),
                                 zoom: Py.round(max(1.0, k0.zoom - (k1.zoom - k0.zoom) * f), 4))
        let end = TransformKey(t: Py.round(loopDur, 3), cx: k0.cx, cy: k0.cy, zoom: k0.zoom)
        var tf = cover
        tf.cx = start.cx
        tf.cy = start.cy
        tf.zoom = start.zoom
        tf.keys = [start, end]
        ctx.items[li].transform = tf
        ctx.items[li].note = "kenburns"
    }

    // MARK: words beside faces

    /// A face on screen as (x, y, w, h) in output coordinates (centre, size; 0..1).
    struct FaceBox4 {
        var x: Double
        var y: Double
        var w: Double
        var h: Double
    }

    /// t → the face on screen at timeline time t, in output coordinates (after the crop and any move), or nil.
    static func faceLookup(_ ctx: CompileContext) -> (Double) -> FaceBox4? {
        let v1 = ctx.items.filter { $0.track == "V1" && ($0.kind == "video" || ($0.kind == "image" && $0.transform != nil)) }
        let pa = ctx.pa, W = Double(ctx.W), H = Double(ctx.H)
        return { t in
            for it in v1 where it.recIn <= t && t < it.recOut {
                guard let assetId = it.assetId else { return nil }
                let st = it.kind == "image" ? 0.0 : it.srcIn + (t - it.recIn) * it.speed
                guard let sh = pa.clips[assetId]?.shots.first(where: { $0.t0 - 1e-3 <= st && st <= $0.t1 + 1e-3 }) else { return nil }
                var boxes: [FaceBox4]
                if !sh.seats.isEmpty {
                    boxes = sh.seats.map { FaceBox4(x: $0.x, y: $0.y, w: $0.w, h: $0.h) }
                } else {
                    let near = sh.faces.filter { abs($0.t - st) <= 1.0 }
                    if !near.isEmpty {
                        boxes = near.map { FaceBox4(x: $0.x, y: $0.y, w: $0.w, h: $0.h) }
                    } else if !sh.faces.isEmpty, !sh.track.isEmpty {     // between face samples: the tracked position, the usual size
                        let p = sh.track.min(by: { abs($0[0] - st) < abs($1[0] - st) })!
                        boxes = [FaceBox4(x: p[1], y: p[2], w: Py.median(sh.faces.map(\.w)), h: Py.median(sh.faces.map(\.h)))]
                    } else {
                        return nil
                    }
                }
                let ds = pa.asset(assetId)?.info.displaySize ?? (ctx.W, ctx.H)
                let dw = Double(ds.w), dh = Double(ds.h)
                let srcAr = dw / dh, outAr = W / H
                if let tf = it.transform, tf.fit {                  // the whole photo, a little above the middle
                    let s = min(W / dw, H / dh)
                    let fw = dw * s / W, fh = dh * s / H
                    let left = (1 - fw) / 2, top = (1 - fh) * 0.45
                    let shown = boxes.map { FaceBox4(x: left + $0.x * fw, y: top + $0.y * fh, w: $0.w * fw, h: $0.h * fh) }
                    return shown.min(by: { abs($0.y - 0.46) < abs($1.y - 0.46) })
                }
                var cx = 0.5, cy = 0.5, z = 1.0
                if it.kind == "image", let tf = it.transform {      // a photo's own move: where it is at time t
                    let now = tf.at(t - it.recIn)
                    cx = now.cx
                    cy = now.cy
                    z = max(1.0, now.zoom)
                } else {
                    z = max(1.0, it.transform?.zoom ?? 1.0)
                    cx = it.transform?.cx ?? 0.5
                    cy = it.transform?.cy ?? 0.5
                }
                let cw = srcAr > outAr ? (outAr / srcAr) / z : 1.0 / z
                let ch = srcAr > outAr ? 1.0 / z : (srcAr / outAr) / z
                let left = min(max(cx - cw / 2, 0.0), 1 - cw), top = min(max(cy - ch / 2, 0.0), 1 - ch)
                let shown = boxes.filter { left <= $0.x && $0.x <= left + cw }
                    .map { FaceBox4(x: ($0.x - left) / cw, y: ($0.y - top) / ch, w: $0.w / cw, h: $0.h / ch) }
                return shown.min(by: { abs($0.x - 0.5) < abs($1.x - 0.5) })
            }
            return nil
        }
    }

    /// Where words on a photo go, and at what size: the middle when it's free (or the top, for a title), else the larger
    /// free band above the head (leaving room for hair) or below the chin, inside the platform's safe area — never across
    /// a face. A tight close-up leaves little room: the words get a little smaller (down to 76 %) to fit.
    static func besideFace(_ ctx: CompileContext, _ fb: FaceBox4?, text: String, pos: String) -> (pos: String, y: Double, scale: Double) {
        let safe = TextLayout.safe(vertical: ctx.H > ctx.W)
        let loY = safe.top + 0.02, hiY = 1 - safe.bottom - 0.01         // the block must sit inside [loY, hiY]
        func clamp(_ y: Double, _ h: Double) -> Double { Py.round(min(max(y, loY + h / 2), hiY - h / 2), 4) }
        func height(_ scale: Double) -> Double { TextLayout.textBlock(text, style: "photo", width: ctx.W, height: ctx.H, scale: scale).height }
        var h = height(1.0)
        let want = pos == "center" ? 0.46 : loY + h / 2
        guard let fb else { return (pos, clamp(want, h), 1.0) }
        let faceTop = fb.y - fb.h / 2 - 0.3 * fb.h, faceBot = fb.y + fb.h / 2 + 0.03     // hair above, a breath below the chin
        if want + h / 2 < faceTop || want - h / 2 > faceBot { return (pos, clamp(want, h), 1.0) }   // already clear
        let above = faceTop - loY, below = hiY - faceBot
        for scale in [1.0, 0.92, 0.84, 0.76] {
            h = height(scale)
            if above >= h && (above >= below || pos == "upper") {
                return ("upper", Py.round(max(loY + h / 2, min((loY + faceTop) / 2, faceTop - h / 2)), 4), scale)
            }
            if below >= h {
                return ("lower", Py.round(min(hiY - h / 2, max((faceBot + hiY) / 2, faceBot + h / 2)), 4), scale)
            }
        }
        // even small it won't fit (an extreme close-up): the bigger band, against its outer edge
        h = height(0.76)
        return above >= below ? ("upper", clamp(loY + h / 2, h), 0.76) : ("lower", clamp(hiY - h / 2, h), 0.76)
    }

    // MARK: music

    /// The song under the cut: one item per pass through the track (looping from the top if it runs out), its level
    /// as an envelope every 50 ms (the music's job, ducked under speech), and the decision with its reason.
    static func layMusic(_ ctx: CompileContext, total: Double) throws {
        let pb = try Knowledge.playbook(ctx.d.playbook)
        let bedDb = pb.music["bed_db"]?.number ?? -20, frontDb = pb.music["front_db"]?.number ?? -8
        for cue in ctx.polish.music {
            guard let s = ctx.sectionT[cue.section], s[1] - s[0] >= 0.3 else { continue }
            ctx.musicSpans.append(MusicSpan(t0: s[0], t1: s[1], mode: Py.text(cue.trackId) != nil ? cue.mode : "none", section: cue.section))
        }
        var groups: [(track: String, parts: [(t0: Double, t1: Double, cue: MusicCue)])] = []
        for cue in ctx.polish.music {
            guard let s = ctx.sectionT[cue.section], let track = Py.text(cue.trackId), cue.mode != "none" else { continue }
            if let last = groups.last, last.track == track, abs(last.parts[last.parts.count - 1].t1 - s[0]) < 0.6 {
                groups[groups.count - 1].parts.append((s[0], s[1], cue))
            } else {
                groups.append((track, [(s[0], s[1], cue)]))
            }
        }
        let muteSpeech = ctx.brief.rules.contains { $0.kind == "no_music_under_speech" }
        for (track, parts) in groups {
            guard let a = ctx.pa.asset(track) else { continue }
            let g0 = parts[0].t0, g1 = parts[parts.count - 1].t1
            let need = g1 - g0
            let m = ctx.pa.clips[track]?.music
            let dropSec = ctx.sectionT["drop"] ?? ctx.sectionT["climax"]
            let align: Double? = dropSec.flatMap { g0 <= $0[0] && $0[0] < g1 ? $0[0] - g0 : nil }
            let start: (offset: Double, why: String)
            if let fixed = parts.lazy.compactMap({ $0.cue.offset }).first {      // the cut was built on this track's beats
                start = (fixed, "starts at \(Py.fixed(fixed, 1))s, where the cut's beat grid begins")
            } else if let m {
                start = Music.bestOffset(m, trackDuration: a.info.duration, need: need, alignDropAt: align)
            } else {
                start = (0.0, "start of track")
            }
            let off = start.offset, why = start.why
            func levels(_ cue: MusicCue) -> (free: Double, speech: Double) {
                let free = cue.mode == "front" ? frontDb : (cue.mode == "bed" ? bedDb + 6 : bedDb + 2)
                let sp = muteSpeech ? -80.0 : (cue.mode == "bed" || cue.mode == "light" ? bedDb : bedDb + 2)
                let g = max(-12.0, min(6.0, cue.gainDb))
                return (min(-1.0, free + g), sp <= -80 ? sp : min(-12.0, sp + g))
            }
            var merged: [[Double]] = []
            for (s0, s1) in ctx.speechSpans.sorted(by: { $0.0 != $1.0 ? $0.0 < $1.0 : $0.1 < $1.1 }) where !(s1 <= g0 || s0 >= g1) {
                if let last = merged.last, s0 - last[1] < 1.0 {
                    merged[merged.count - 1][1] = max(last[1], s1)
                } else {
                    merged.append([s0, s1])
                }
            }
            func levelAt(_ tt: Double) -> Double {
                let cue = parts.first(where: { $0.t0 - 1e-6 <= tt && tt <= $0.t1 + 1e-6 })?.cue ?? parts[parts.count - 1].cue
                let (free, sp) = levels(cue)
                var lvl = free
                for s in merged {
                    let s0 = s[0], s1 = s[1]
                    if s0 <= tt && tt <= s1 { return sp }
                    if s0 - 0.25 <= tt && tt < s0 {
                        lvl = min(lvl, sp + (free - sp) * (s0 - tt) / 0.25)
                    } else if s1 < tt && tt <= s1 + 0.4 {
                        lvl = min(lvl, sp + (free - sp) * (tt - s1) / 0.4)
                    }
                }
                return lvl
            }
            let grid = Py.arange(g0, g1 + 0.05, 0.05)
            let vals = grid.map(levelAt)
            var clean: [[Double]] = []
            for (k, (tt, db)) in zip(grid, vals).enumerated() {
                let prev: Double? = k > 0 ? vals[k - 1] : nil
                let next: Double? = k + 1 < vals.count ? vals[k + 1] : nil
                if k == 0 || next == nil || abs(db - (prev ?? db)) > 1e-3 || abs(db - (next ?? db)) > 1e-3 {
                    clean.append([Py.round(tt, 3), Py.round(db, 2)])
                }
            }
            var pos = g0, curOff = off, guardN = 0
            while pos < g1 - 0.05 && guardN < 50 {
                guardN += 1
                var avail = a.info.duration - curOff
                if avail < 1.0 {                                     // end of the track: loop from the top
                    curOff = 0.0
                    avail = a.info.duration
                }
                if avail < 1.0 { break }
                let segLen = min(g1 - pos, avail)
                let p0 = pos
                ctx.items.append(Item(id: ctx.iid("m"), track: "A2", kind: "audio", assetId: a.id, srcIn: Py.round(curOff, 3),
                                      srcOut: Py.round(curOff + segLen, 3), recIn: Py.round(pos, 3), gainDb: 0.0,
                                      envelope: clean.filter { p0 - 0.01 <= $0[0] && $0[0] <= p0 + segLen + 0.01 },
                                      fadeIn: pos == g0 ? 0.05 : 1.0, fadeOut: pos + segLen >= g1 - 0.05 ? 1.5 : 1.0, role: "music",
                                      section: parts[0].cue.section))
                pos += segLen
                curOff = 0.0
            }
            let modes = Set(parts.map { $0.cue.mode }).sorted(by: Py.less).map { musicWords[$0] ?? $0 }.joined(separator: " and ")
            ctx.suggest("music", "\(a.name) \(modes) (\(parts[0].cue.why)); \(why)", conf: 0.8, t: g0, alts: parts[0].cue.alternatives,
                        payload: ["track": .string(a.id), "offset": .number(off), "key": .string("music:" + parts.map { $0.cue.section }.joined(separator: ",")),
                                  "sections": .array(parts.map { .string($0.cue.section) })])
        }
        for cue in ctx.polish.music where cue.mode != "none" && Py.text(cue.trackId) == nil {
            guard let s = ctx.sectionT[cue.section] else { continue }
            ctx.suggest("music", "No suitable track for “\(cue.section)” in your music folder — search: \(cue.brief.searchTerms.prefix(2).joined(separator: ", "))",
                        conf: 0.4, t: s[0], status: "optional",
                        payload: ["search": .array(cue.brief.searchTerms.map { .string($0) }), "key": .string("music:\(cue.section)"), "acceptable": .bool(false)])
        }
    }
}

/// What the compiler builds up while it lays out one timeline.
final class CompileContext {
    let pa: ProjectAnalysis
    let d: Direction
    let story: StoryPlan
    let polish: PolishPlan
    let brief: CreatorBrief
    let W: Int
    let H: Int
    let fps: Double
    var items: [Item] = []
    var sugg: [Suggestion] = []
    var markers: [Marker] = []
    var spans: [String: [(Double, Double)]] = [:]               // story ref → its spans on the timeline
    var sectionT: [String: [Double]] = [:]                      // section → [start, end]
    var speechSpans: [(Double, Double)] = []
    var musicSpans: [MusicSpan] = []
    var nPhotos = 0                                             // photos placed so far (the motion alternates)
    var nItems = 0
    var nSugg = 0

    init(pa: ProjectAnalysis, d: Direction, story: StoryPlan, polish: PolishPlan, brief: CreatorBrief, W: Int, H: Int, fps: Double) {
        self.pa = pa
        self.d = d
        self.story = story
        self.polish = polish
        self.brief = brief
        self.W = W
        self.H = H
        self.fps = fps
    }

    func iid(_ prefix: String) -> String {
        nItems += 1
        return "\(prefix)\(nItems)"
    }

    /// One decision with its reason; one with a time also gets a marker on the timeline.
    @discardableResult
    func suggest(_ type: String, _ reason: String, source: String = "rules", conf: Double = 0.8, t: Double? = nil, items: [String] = [],
                 status: String? = nil, alts: [String] = [], payload: [String: JSONValue] = [:]) -> Suggestion {
        nSugg += 1
        let st = status ?? (conf >= 0.5 ? "applied" : "optional")
        let s = Suggestion(id: "sg\(nSugg)", type: type, status: st, confidence: Py.round(conf, 2), reason: reason, source: source,
                           t: t.map { Py.round($0, 3) }, itemIds: items, payload: payload, alternatives: alts)
        sugg.append(s)
        if let t {
            markers.append(Marker(t: Py.round(t, 3), name: type, note: Py.prefix(reason, 140), color: st == "applied" ? "green" : "yellow",
                                  suggestionId: s.id))
        }
        return s
    }
}
