import AVFoundation
import XCTest
@testable import PreProCore

/// A song file goes in, the desktop's beats come out: AudioDecoder reads it as 22.05 kHz mono (librosa.load's way) and
/// the analysis finds the same tempo and beats as the desktop did on the same song.
final class AudioDecoderTests: XCTestCase {
    func writeWav(_ channels: [[Float]], sampleRate: Double) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("prepro-\(UUID().uuidString).wav")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: sampleRate, AVNumberOfChannelsKey: channels.count,
            AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true, AVLinearPCMIsBigEndianKey: false, AVLinearPCMIsNonInterleaved: false,
        ]
        do {                                                   // the file is finished when the writer goes away
            let file = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
            let n = channels[0].count
            let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(n)))
            buffer.frameLength = AVAudioFrameCount(n)
            for (c, samples) in channels.enumerated() {
                samples.withUnsafeBufferPointer { buffer.floatChannelData![c].update(from: $0.baseAddress!, count: n) }
            }
            try file.write(from: buffer)
            file.close()                                       // finish the file before anyone reads it
        }
        return url
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

    func happy() -> (sections: [SongSynth.Section], seed: UInt64) {
        ([SongSynth.Section("intro", 2, 0.3), SongSynth.Section("verse", 4, 0.6), SongSynth.Section("chorus", 8, 0.9),
          SongSynth.Section("outro", 2, 0.35)], 16)
    }

    func golden() throws -> MusicInfo {
        let dir = try XCTUnwrap(Bundle.module.url(forResource: "Golden", withExtension: nil))
        let data = try Data(contentsOf: dir.appendingPathComponent("songs/happy_100.json"))
        struct G: Decodable { let music: MusicInfo }
        return try JSONDecoder().decode(G.self, from: data).music
    }

    func testAWavAtTheAnalysisRateReadsBackExactly() throws {
        let (sections, seed) = happy()
        let y = SongSynth.song(bpm: 100, sections: sections, minor: false, seed: seed, sampleRate: 22050).0
        let url = try writeWav([y], sampleRate: 22050)
        defer { try? FileManager.default.removeItem(at: url) }
        let back = try AudioDecoder.load(url)
        XCTAssertEqual(back.count, y.count)
        XCTAssertEqual(back, y, "float32 in, the same float32 out")
        let beats = BeatTracker.track(back)
        let want = try golden()
        XCTAssertEqual(Py.round(beats.bpm, 2), want.bpm, accuracy: 1e-9)
        XCTAssertEqual(beats.frames.count, want.beats.count)
        for (a, b) in zip(beats.times, want.beats) { XCTAssertEqual(a, b, accuracy: 0.024) }
    }

    func testAStereoSongAt44kIsMixedAndResampled() throws {
        let (sections, seed) = happy()
        let y = SongSynth.song(bpm: 100, sections: sections, minor: false, seed: seed, sampleRate: 44100).0
        let url = try writeWav([y, y], sampleRate: 44100)
        defer { try? FileManager.default.removeItem(at: url) }
        let back = try AudioDecoder.load(url)
        XCTAssertEqual(back.count, Int((Double(y.count) * 22050 / 44100).rounded(.up)), "librosa's length: ceil(n · 22050 / 44100)")
        let info = MusicAnalysis.analyze(back)
        let want = try golden()
        XCTAssertEqual(info.bpm, want.bpm, accuracy: 1e-9, "the same tempo from a 44.1 kHz stereo file")
        XCTAssertLessThanOrEqual(abs(info.beats.count - want.beats.count), 1)
        let matched = want.beats.filter { b in info.beats.contains { abs($0 - b) < 0.05 } }.count
        XCTAssertGreaterThanOrEqual(matched, want.beats.count - 1, "beats where the desktop hears them")
        XCTAssertEqual(info.sections.map(\.label), want.sections.map(\.label))
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
