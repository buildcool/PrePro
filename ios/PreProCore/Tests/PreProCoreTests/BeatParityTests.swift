import XCTest
@testable import PreProCore

/// The phone hears a song's beat the way the desktop does. Golden/songs holds the desktop's librosa analysis of test
/// songs both apps make sample for sample (scripts/portable_song.py ↔ Fixtures/SongSynth.swift): the same song, the
/// same onset envelope, librosa's exact tempo bin and beat frames.
final class BeatParityTests: XCTestCase {
    struct SongGolden: Decodable {
        struct Params: Decodable {
            let bpm: Double
            let minor: Bool?
            let key: String?
            let seed: UInt64
            let sections: [[JSONValue]]
            let sr: Double
        }

        let params: Params
        let samples: Int
        let probe: [String: Double]
        let energy: Double
        let onset: [Double]
        let tempo: Double
        let beat_frames: [Int]
        let music: MusicInfo
    }

    let songs = ["happy_100", "warm_92", "trap_140", "ballad_64"]

    func golden(_ name: String) throws -> SongGolden {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil), "Golden folder not bundled")
        let data = try Data(contentsOf: dir.appendingPathComponent("songs").appendingPathComponent("\(name).json"))
        return try JSONDecoder().decode(SongGolden.self, from: data)
    }

    func synth(_ g: SongGolden) -> [Float] {
        let sections = g.params.sections.map { s in
            SongSynth.Section(s[0].string ?? "", Int(s[1].number ?? 0), s[2].number ?? 0)
        }
        return SongSynth.song(bpm: g.params.bpm, sections: sections, key: g.params.key ?? "A", minor: g.params.minor ?? true,
                              seed: g.params.seed, sampleRate: g.params.sr).0
    }

    func testThePhoneMakesTheSameSongs() throws {
        for name in songs {
            let g = try golden(name)
            let y = synth(g)
            XCTAssertEqual(y.count, g.samples, "\(name): length")
            for (i, want) in g.probe {
                guard let k = Int(i), k < y.count else { continue }
                XCTAssertEqual(Double(y[k]), want, accuracy: 2e-6, "\(name): sample \(k)")
            }
            let energy = y.reduce(0.0) { $0 + Double($1) * Double($1) }
            XCTAssertEqual(energy, g.energy, accuracy: g.energy * 1e-6, "\(name): energy")
        }
    }

    func testOnsetStrengthIsLibrosas() throws {
        for name in songs {
            let g = try golden(name)
            let onset = BeatTracker.onsetStrength(synth(g))
            XCTAssertEqual(onset.count, g.onset.count, "\(name): frames")
            let worst = zip(onset, g.onset).map { abs(Double($0) - $1) }.max() ?? 0
            XCTAssertLessThan(worst, 1e-3, "\(name): the onset envelope strays from librosa's by \(worst)")
        }
    }

    func testTheTrackerLandsOnLibrosasBeatFrames() throws {
        for name in songs {
            let g = try golden(name)
            let onset = g.onset.map { Float($0) }                 // librosa's own envelope, exactly
            let bpm = BeatTracker.tempo(onset)
            XCTAssertEqual(bpm, g.tempo, accuracy: 1e-9, "\(name): tempo bin")
            XCTAssertEqual(BeatTracker.beatFrames(onset, bpm: g.tempo), g.beat_frames, "\(name): beat frames")
        }
    }

    func testThePhoneHearsTheSameBeats() throws {
        for name in songs {
            let g = try golden(name)
            let beats = BeatTracker.track(synth(g))
            XCTAssertEqual(Py.round(beats.bpm, 2), g.music.bpm, accuracy: 1e-9, "\(name): BPM")
            XCTAssertEqual(beats.frames.count, g.music.beats.count, "\(name): beats")
            for (got, want) in zip(beats.times, g.music.beats) {
                XCTAssertEqual(got, want, accuracy: 0.024, "\(name): a beat moved by more than a frame")
            }
        }
    }

    func testNumpysPairwiseSum() {
        let x = (0..<1000).map { Float($0) * 0.1 }
        XCTAssertEqual(DSP.pairwiseSum(x[...]), 49950.0, accuracy: 0.01)
        let w = DSP.hann(2048)
        XCTAssertEqual(w[0], 0)
        XCTAssertEqual(w[1024], 1)
        XCTAssertEqual(w[512], w[1536], accuracy: 1e-15)
    }
}
