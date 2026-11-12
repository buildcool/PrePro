import AVFoundation
import XCTest
@testable import PreProCore

/// A song file goes in, the desktop's beats come out: AudioDecoder reads it as 22.05 kHz mono (librosa.load's way) and
/// the analysis hears what the desktop heard in the same file.
final class AudioDecoderTests: XCTestCase {
    /// A float32 WAV written byte by byte (RIFF, IEEE float, a fact chunk, interleaved channels): exactly these samples.
    func writeWav(_ channels: [[Float]], sampleRate: Double) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("prepro-\(UUID().uuidString).wav")
        let ch = channels.count, n = channels[0].count
        var data = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
        let dataBytes = UInt32(n * ch * 4)
        data.append(contentsOf: Array("RIFF".utf8))
        u32(4 + (8 + 16) + (8 + 4) + (8 + dataBytes))
        data.append(contentsOf: Array("WAVE".utf8))
        data.append(contentsOf: Array("fmt ".utf8))
        u32(16)
        u16(3)                                                 // WAVE_FORMAT_IEEE_FLOAT
        u16(UInt16(ch))
        u32(UInt32(sampleRate))
        u32(UInt32(sampleRate) * UInt32(ch) * 4)
        u16(UInt16(ch * 4))
        u16(32)
        data.append(contentsOf: Array("fact".utf8))
        u32(4)
        u32(UInt32(n))
        data.append(contentsOf: Array("data".utf8))
        u32(dataBytes)
        var interleaved = [Float](repeating: 0, count: n * ch)
        for i in 0..<n {
            for c in 0..<ch { interleaved[i * ch + c] = channels[c][i] }
        }
        interleaved.withUnsafeBytes { data.append(contentsOf: $0) }
        try data.write(to: url)
        return url
    }

    struct SongFile: Decodable {
        struct From44k: Decodable {
            let samples_44k: Int
            let samples: Int
            let music: MusicInfo
        }

        let music: MusicInfo
        let from_44k: From44k?
    }

    func golden() throws -> SongFile {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil))
        return try JSONDecoder().decode(SongFile.self, from: Data(contentsOf: dir.appendingPathComponent("songs/happy_100.json")))
    }

    func happy(_ sr: Double) -> [Float] {
        let sections = [SongSynth.Section("intro", 2, 0.3), SongSynth.Section("verse", 4, 0.6), SongSynth.Section("chorus", 8, 0.9),
                        SongSynth.Section("outro", 2, 0.35)]
        return SongSynth.song(bpm: 100, sections: sections, minor: false, seed: 16, sampleRate: sr).0
    }

    func testResamplingKeepsTheWholeSignal() throws {
        // a 440 Hz tone, 3 s at 44.1 kHz: at 22.05 kHz it keeps its length, its loudness and its pitch to the end
        let x = (0..<132_300).map { Float(0.5 * sin(2 * Double.pi * 440 * Double($0) / 44100)) }
        let y = try AudioDecoder.resample(x, from: 44100, to: 22050)
        XCTAssertEqual(y.count, 66_150)
        let tail = Array(y[60_000..<66_000])                    // the last part, where a dropped input would show as silence
        let rms = (tail.map { Double($0) * Double($0) }.reduce(0, +) / Double(tail.count)).squareRoot()
        XCTAssertEqual(rms, 0.5 / 2.0.squareRoot(), accuracy: 0.01)
        let crossings = zip(y.dropFirst(1000), y.dropFirst(1001)).filter { $0 < 0 && $1 >= 0 }.count
        XCTAssertEqual(Double(crossings), 440 * (66_150 - 1001) / 22050.0, accuracy: 3)
    }

    func testAWavAtTheAnalysisRateReadsBackExactly() throws {
        let y = happy(22050)
        let url = try writeWav([y], sampleRate: 22050)
        defer { try? FileManager.default.removeItem(at: url) }
        let back = try AudioDecoder.load(url)
        XCTAssertEqual(back.count, y.count, "every frame, to the last")
        XCTAssertTrue(back == y, "float32 in, the same float32 out")
        let beats = BeatTracker.track(back)
        let want = try golden().music
        XCTAssertEqual(Py.round(beats.bpm, 2), want.bpm, accuracy: 1e-9)
        XCTAssertEqual(beats.frames.count, want.beats.count)
        for (a, b) in zip(beats.times, want.beats) { XCTAssertEqual(a, b, accuracy: 0.024) }
    }

    func testAStereoSongAt44kSoundsAsItDoesOnTheDesktop() throws {
        let file = try XCTUnwrap(try golden().from_44k, "the 44.1 kHz golden")
        let y = happy(44100)
        XCTAssertEqual(y.count, file.samples_44k, "the phone makes the same 44.1 kHz song")
        let url = try writeWav([y, y], sampleRate: 44100)
        defer { try? FileManager.default.removeItem(at: url) }
        let back = try AudioDecoder.load(url)
        XCTAssertEqual(back.count, file.samples, "librosa's length: ceil(n · 22050 / 44100)")
        let info = MusicAnalysis.analyze(back)
        let want = file.music
        XCTAssertEqual(info.bpm, want.bpm, accuracy: 1e-9, "the tempo the desktop hears in this file")
        XCTAssertLessThanOrEqual(abs(info.beats.count - want.beats.count), 1, "beats")
        let matched = want.beats.filter { b in info.beats.contains { abs($0 - b) < 0.024 } }.count
        XCTAssertGreaterThanOrEqual(matched, want.beats.count - 1, "beats where the desktop hears them")
        XCTAssertEqual(info.sections.map(\.label), want.sections.map(\.label), "the song's parts")
    }

    func testANonAudioFileSaysWhy() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("prepro-\(UUID().uuidString).wav")
        try Data("not audio".utf8).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertThrowsError(try AudioDecoder.load(url)) { error in
            XCTAssertTrue("\(error)".contains("couldn't read the song"))
        }
    }
}
