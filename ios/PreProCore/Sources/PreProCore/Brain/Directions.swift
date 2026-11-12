import Foundation

/// The cut to make of a shoot of photos — the desktop's BasicBrain.directions / target_length / hook_options /
/// direction_name / outline for a photo reel: its length (about 1.2 s a photo and a held cover; one photo: as long as
/// your lines take), the cover (the most striking photo, with the next two as "another cover"), its name and outline.
/// Footage the phone can't cut yet (talking, video clips) is refused, not guessed.
extension RulesBrain {
    static let lookByPlaybook = ["story_vlog": "warm", "travel_film": "teal_orange", "hype_reel": "punchy", "aesthetic": "pastel",
                                 "teaser": "teal_orange", "talking_head": "natural", "podcast_clip": "natural", "gaming": "punchy",
                                 "comedy": "natural", "day_in_life": "natural", "text_reel": "natural"]
    static let paceByPlaybook = ["hype_reel": 0.9, "teaser": 0.8, "aesthetic": 0.25, "travel_film": 0.6, "day_in_life": 0.55]

    public func directions(max maxN: Int = 4) throws -> [Direction] {
        if pa.assets.contains(where: { ["aroll", "broll", "screen"].contains($0.kind) }) {
            throw BrainError.notOnPhoneYet("video clips")
        }
        let prefs = brief.prefs
        var keys: [(playbook: String, score: Double, why: String, fromBrief: Bool)] = []
        if let p = Py.text(prefs.playbook) { keys.append((p, 1.0, "what your brief asked for", true)) }
        for g in pa.genres where g.score >= 0.35 && !keys.contains(where: { $0.playbook == g.playbook }) {
            keys.append((g.playbook, g.score, g.why, false))
        }
        if keys.isEmpty { keys = [("story_vlog", 0.4, "default", false)] }
        var out: [Direction] = []
        for (i, k) in keys.prefix(maxN).enumerated() {
            guard k.playbook == "photo_reel" else { throw BrainError.notOnPhoneYet(k.playbook) }
            let pb = try Knowledge.playbook(k.playbook)
            let aspect = (k.fromBrief || (Py.text(prefs.aspect) != nil && i == 0) ? Py.text(prefs.aspect) : nil) ?? pb.aspect
            var target = try targetLength(k.playbook)
            if k.fromBrief || i == 0, let t = Py.number(prefs.targetLength) { target = t }
            for r in rules where r.kind == "max_length" {
                if case .number(let v)? = r.value { target = min(target, v) }
            }
            let capDefault = pb.captions["default"]?.string ?? "clean"
            var knobs = Knobs(pace: prefs.pace ?? Self.paceByPlaybook[k.playbook] ?? 0.5, effects: Py.text(prefs.effects) ?? "balanced",
                              captions: Py.text(prefs.captions) ?? capDefault,
                              humour: Py.text(prefs.humour) ?? (["light", "allowed", "comedic_only"].contains(pb.memes) ? "light" : "off"),
                              targetLength: target, freedom: prefs.freedom, look: Py.text(prefs.look) ?? Self.lookByPlaybook[k.playbook],
                              memeFlavour: Py.text(prefs.memeFlavour) ?? "global")
            if rules.contains(where: { $0.kind == "captions" && $0.value?.string == "off" }) { knobs.captions = "off" }
            var d = Direction(id: "d\(i + 1)", playbook: k.playbook, name: try directionName(k.playbook, aspect: aspect, target: target),
                              aspect: aspect, targetMin: Py.round(max(5.0, target * 0.85), 1), targetMax: Py.round(target * 1.15, 1),
                              fitScore: Py.round(k.score, 3), why: k.why, hooks: try hookOptions(k.playbook), knobs: knobs,
                              fromBrief: k.fromBrief)
            d.outline = try outline(d)
            out.append(d)
        }
        return out
    }

    /// target_length for a photo reel: ≈ 1.2 s a photo + a held cover; one photo: two to four phrases (your lines).
    func targetLength(_ playbook: String) throws -> Double {
        let pb = try Knowledge.playbook(playbook)
        guard playbook == "photo_reel" else { throw BrainError.notOnPhoneYet(playbook) }
        let n = photos().count
        let est = n <= 1 ? 10.0 + 3.5 * Double(max(0, textLines().count - 2)) : 2.4 + 1.2 * Double(n)
        let hi = pb.target.count > 1 ? pb.target[1] : est
        return Py.round(min(est, hi), 1)                       // np.clip(est, min(lo, est), hi)
    }

    func directionName(_ playbook: String, aspect: String, target: Double) throws -> String {
        let pb = try Knowledge.playbook(playbook)
        let fmt = aspect == "9:16" ? "Reel/Short" : "YouTube"
        let t = target >= 120 ? Py.fixed(target / 60, 0) + " min" : Py.fixed(target, 0) + " s"
        return "\(pb.name) · \(fmt) · ~\(t)"
    }

    /// hook_options for a photo reel: the cover and the next two best, so "another cover" in the review has somewhere
    /// to go (after a hook your brief asked for).
    func hookOptions(_ playbook: String) throws -> [HookOption] {
        let pb = try Knowledge.playbook(playbook)
        var opts: [HookOption] = []
        if let forced = rules.first(where: { $0.kind == "hook" && !$0.target.isEmpty }) {
            opts.append(HookOption(id: "h0", kind: "from_brief", refs: [forced.target], textHook: nil, why: "you asked: “\(forced.anchor)”",
                                   score: 1.0))
        }
        if playbook == "photo_reel" {
            let covers = photos().stableSorted { a, b in
                let x = coverScore(a), y = coverScore(b)
                return x.0 != y.0 ? x.0 > y.0 : x.1 > y.1
            }
            let title = photoTitle()
            for (k, cover) in covers.prefix(3).enumerated() {
                let why = (k == 0 ? "open on your most striking photo" : "or open on this photo") + " (\(cover.assetId)): colour, contrast"
                    + (cover.faces.isEmpty ? "" : " and a face") + " stop the scroll"
                opts.append(HookOption(id: "h\(opts.count)", kind: "visual_spectacle", refs: [cover.id], textHook: title, why: why,
                                       score: Py.round((0.6 + 0.4 * (cover.aesthetic ?? 0)) * (1.0 - 0.1 * Double(k)), 3)))
            }
        }
        let allowed = Set(pb.hooks).union(["from_brief"])
        func key(_ o: HookOption) -> Double { -(o.score + (allowed.contains(o.kind) ? 0.1 : 0)) }
        return Array(opts.stableSorted { key($0) < key($1) }.prefix(3))
    }

    /// outline: the hook, then the structure (a photo shoot has no talking or video places to list).
    func outline(_ d: Direction) throws -> [String] {
        let pb = try Knowledge.playbook(d.playbook)
        var lines: [String] = []
        if let h = d.hooks.first {
            lines.append("Hook (\(h.kind.replacingOccurrences(of: "_", with: " "))): shot \(h.refs.first ?? "")")
        }
        lines.append("Structure: " + pb.structure.joined(separator: " → "))
        return lines
    }
}
