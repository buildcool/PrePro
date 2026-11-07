import AVFoundation
import Foundation

public enum AudioDecoderError: Error, CustomStringConvertible {
    case unreadable(String)

    public var description: String {
        switch self {
        case .unreadable(let why): return "couldn't read the song: \(why)"
        }
    }
}

/// A song file as the analysis hears it — 22.05 kHz mono float samples, the first ten minutes (the desktop's
/// librosa.load(sr=22050, mono=True, duration=600)). Channels are averaged by hand, as librosa does, then resampled at
/// the converter's best quality.
public enum AudioDecoder {
    public static func load(_ url: URL, sampleRate target: Double = 22050, maxSeconds: Double = 600) throws -> [Float] {
        let file: AVAudioFile
        do {
            file = try AVAudioFile(forReading: url)
        } catch {
            throw AudioDecoderError.unreadable(error.localizedDescription)
        }
        let format = file.processingFormat                      // float32, one buffer per channel
        let frames = AVAudioFrameCount(min(Double(file.length), maxSeconds * format.sampleRate))
        guard frames > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return [] }
        do {
            try file.read(into: buffer, frameCount: frames)
        } catch {
            throw AudioDecoderError.unreadable(error.localizedDescription)
        }
        guard let channels = buffer.floatChannelData else { throw AudioDecoderError.unreadable("not float audio") }
        let n = Int(buffer.frameLength), count = Int(format.channelCount)
        var mono = [Float](repeating: 0, count: n)
        for i in 0..<n {
            var s: Float = 0
            for c in 0..<count { s += channels[c][i] }
            mono[i] = count == 1 ? s : s / Float(count)
        }
        if abs(format.sampleRate - target) < 0.5 { return mono }
        return try resample(mono, from: format.sampleRate, to: target)
    }

    /// Mono float samples from one rate to another (AVAudioConverter at its best quality).
    public static func resample(_ x: [Float], from rate: Double, to target: Double) throws -> [Float] {
        guard !x.isEmpty,
              let inFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate, channels: 1, interleaved: false),
              let outFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: target, channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: inFormat, to: outFormat),
              let input = AVAudioPCMBuffer(pcmFormat: inFormat, frameCapacity: AVAudioFrameCount(x.count)) else {
            return []
        }
        converter.sampleRateConverterQuality = AVAudioQuality.max.rawValue
        converter.sampleRateConverterAlgorithm = AVSampleRateConverterAlgorithm_Mastering
        input.frameLength = AVAudioFrameCount(x.count)
        x.withUnsafeBufferPointer { input.floatChannelData![0].update(from: $0.baseAddress!, count: x.count) }
        let expected = Int((Double(x.count) * target / rate).rounded())
        var out = [Float]()
        out.reserveCapacity(expected + 1024)
        var fed = false
        while true {
            guard let chunk = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: 65536) else { break }
            var error: NSError?
            let status = converter.convert(to: chunk, error: &error) { _, inputStatus in
                if fed {
                    inputStatus.pointee = .endOfStream
                    return nil
                }
                fed = true
                inputStatus.pointee = .haveData
                return input
            }
            if let error { throw AudioDecoderError.unreadable(error.localizedDescription) }
            let got = Int(chunk.frameLength)
            if got > 0, let data = chunk.floatChannelData {
                out.append(contentsOf: UnsafeBufferPointer(start: data[0], count: got))
            }
            if status == .endOfStream || status == .error || (got == 0 && fed) { break }
        }
        // the same length librosa's resampler gives: ceil(n · target / rate)
        let want = Int((Double(x.count) * target / rate).rounded(.up))
        if out.count > want { out.removeLast(out.count - want) }
        if out.count < want { out += [Float](repeating: 0, count: want - out.count) }
        return out
    }
}
