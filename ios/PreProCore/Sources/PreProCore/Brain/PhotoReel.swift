import Foundation

/// Photo reels: your photos in the order you took them, cut on the beat of your song, the most striking one as the
/// cover, your words on them — a port of the desktop's _story_photo_reel / _polish_photo_reel.
extension RulesBrain {
    /// What makes the first frame of a Reel: a striking photo with a person in it that fills the 9:16 frame edge to
    /// edge (a portrait-orientation photo does), never one that has to be shown framed on a blurred fill.
    func coverScore(_ s: Shot) -> (Double, Double) {
        let ds = pa.asset(s.assetId)?.info.displaySize
        let fills = Visual.photoFills(ds, faces: s.faces, outAspect: 9.0 / 16.0)
        let tall = ds.map { $0.h > $0.w } ?? false
        var score = s.aesthetic ?? 0                   // the desktop's order of additions, for the same last digit
        score += 0.15 * (s.faces.isEmpty ? 0 : 1)
        score += 0.08 * (tall ? 1 : 0)
        score -= fills ? 0.0 : 0.6
        return (score, s.sharpness)
    }

    func storyPhotoReel(_ d: Direction) throws -> StoryPlan? {
        let shots = photos()
        guard !shots.isEmpty else { return nil }
        let lines = textLines()
        var grid = try reelGrid(need: Py.number(d.knobs.targetLength) ?? 15.0)
        let p = grid.beat
        let cost = { (n: Int) in abs(Double(n) * p - 1.2) }
        let k = [1, 2, 4].min(by: { cost($0) < cost($1) }) ?? 2      // ≈ 1.2 s a photo, in whole beats (100 BPM → 2 beats)
        var j = 0                                            // beats used so far: every cut lands on a detected beat

        func take(_ n: Int) -> Double {
            let a = grid.time(ofBeat: j), b = grid.time(ofBeat: j + n)
            j += n
            return Py.round(b - a, 3)
        }

        func beatsFor(_ text: String?, base: Int, unit: Int) -> Int {
            var n = base
            if let text = Py.text(text), p > 0 {             // long enough to read: ≈ 3 words a second + time to find it
                let reading = 0.75 + Double(Py.words(text).count) / 3.0
                while Double(n) * p < reading { n += unit }
            }
            return n
        }

        var items: [StoryItem] = []
        let sections = [StorySection(name: "reel", musicMode: "front")]
        if shots.count == 1 {
            // one photo, your words, the song: your first line is on the first frame (it is the hook), every next line
            // arrives on the beat, half a bar at a time, and stays up long enough to read; the last one holds to the end
            let unit = p >= 0.45 ? 2 : 4
            var slots: [ReelGrid.Slot] = []
            for t in lines {
                let n = beatsFor(t, base: unit, unit: unit)
                slots.append(.init(from: j, to: j + n))
                j += n
            }
            j += lines.isEmpty ? 16 : 2 * unit                // no words: four bars of the photo and the song
            let total = Py.round(grid.time(ofBeat: j) - grid.time(ofBeat: 0), 3)
            items.append(StoryItem(ref: shots[0].id, role: "hook", t0: 0, t1: total, section: "reel",
                                   note: "one photo held while your lines land on the music's beat", beats: j))
            grid.lines = lines
            grid.slots = slots
            grid.end = j
            reel = grid
            return StoryPlan(directionId: d.id, items: items, sections: sections,
                             why: "one photo, your words and the song: your first line from the first frame, each next line on the beat")
        }
        let cover = shots.max(by: { coverScore($0) < coverScore($1) })!
        var rest = shots.filter { $0.id != cover.id }
        let target = d.targetMax != 0 ? d.targetMax : (Py.number(d.knobs.targetLength) ?? 30) * 1.15
        let loop = shots.count >= 4 ? k : 0
        // too many photos for the length: the least striking middle ones go (the order stays the order they were taken)
        while !rest.isEmpty && Double(2 * k + rest.count * k + loop) * p > target && rest.count > 2 {
            let middle = Array(rest.dropFirst().dropLast())
            let weakest = (middle.isEmpty ? rest : middle).min(by: { ($0.aesthetic ?? 0) < ($1.aesthetic ?? 0) })!
            rest.remove(at: rest.firstIndex(where: { $0.id == weakest.id })!)
        }
        let texts: [String?] = (0...rest.count).map { $0 < lines.count ? lines[$0] : nil }
        var n = beatsFor(texts[0], base: 2 * k, unit: k)
        items.append(StoryItem(ref: cover.id, role: "hook", t0: 0, t1: take(n), section: "reel",
                               note: "cover: your most striking photo first", beats: n))
        for (i, s) in rest.enumerated() {
            let last = i + 1 == rest.count
            n = beatsFor(texts[i + 1], base: last ? 2 * k : k, unit: k)
            items.append(StoryItem(ref: s.id, role: "photo", t0: 0, t1: take(n), section: "reel",
                                   note: last ? "the last photo holds a little longer" : "", beats: n))
        }
        if shots.count >= 4 && !no.contains("loop") {
            items.append(StoryItem(ref: cover.id, role: "loop", t0: 0, t1: take(k), section: "reel",
                                   note: "loop ending: back to the cover so the Reel replays seamlessly", beats: k))
        }
        grid.k = k
        grid.lines = lines
        reel = grid
        let from = grid.part.map { "its \($0)" } ?? "a downbeat"
        return StoryPlan(directionId: d.id, items: items, sections: sections,
                         why: "cut on the beat of the song (\(Py.fixed(grid.bpm, 0)) BPM, from \(from)): every photo lasts \(k) beat(s)")
    }

    /// Music fixed on the reel's beat grid; your lines (or where and when) on the photos.
    func polishPhotoReel(_ d: Direction, story: StoryPlan, _ pp: inout PolishPlan) throws {
        var r: ReelGrid
        if let saved = reel {
            r = saved
        } else {
            r = try reelGrid(need: 15.0)
            r.k = 2
            r.lines = textLines()
        }
        if let track = Py.text(r.track), !no.contains("music") {
            let part = r.part.map { ", the \($0)" } ?? ""
            pp.music = [MusicCue(section: "reel", mode: "front", trackId: track,
                                 why: "\(Py.fixed(r.bpm, 0)) BPM — the photos change on its beats; it starts at \(Py.fixed(r.offset, 1))s\(part)",
                                 offset: r.offset)]
        }
        if no.contains("text") { return }
        let lines = r.lines
        if story.items.count == 1 && !lines.isEmpty && !r.slots.isEmpty {
            // one photo: each line replaces the last on the beat; the last one stays until the end
            let zero = r.time(ofBeat: 0)
            for (i, (line, slot)) in zip(lines, r.slots).enumerated() {
                let t0 = r.time(ofBeat: slot.from) - zero
                let t1 = r.time(ofBeat: i == lines.count - 1 ? (r.end ?? slot.to) : slot.to) - zero
                pp.effects.append(EffectCue(type: "text", at: "t:\(Py.fixed(t0, 3))", text: line, style: "photo",
                                            dur: Py.round(t1 - t0 - 0.05, 3), intent: "brief",
                                            why: "your line \(i + 1)" + (i == 0 ? ", from the first frame: it is the hook" : ", on the beat"),
                                            confidence: 1.0, position: "center"))
            }
            return
        }
        let title = photoTitle()
        if !lines.isEmpty {
            // line i on photo i (the cover is photo 0): anchored to the photo, not a clock time, so dropping or adding a
            // photo in the review moves the words with the pictures
            let photosShown = story.items.filter { $0.role != "loop" }.count
            for (i, line) in lines.prefix(photosShown).enumerated() {
                pp.effects.append(EffectCue(type: "text", at: "photo:\(i)", text: line, style: "photo", dur: nil, intent: "brief",
                                            why: "your line \(i + 1), on photo \(i + 1)", confidence: 1.0, position: "center"))
            }
        } else if let title = Py.text(title) {
            pp.effects.append(EffectCue(type: "text", at: "photo:0", text: title, style: "photo",
                                        why: "where and when, from your photos — on the cover only", confidence: 0.8, position: "upper"))
        }
    }
}
