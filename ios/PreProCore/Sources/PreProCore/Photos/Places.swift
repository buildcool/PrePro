import Foundation

/// Where a photo was taken, in words, without asking anyone: the desktop's offline lookup (analyze/context.py
/// `place_name`, reverse_geocoder) — the nearest town of GeoNames' cities1000 list (CC BY 4.0, geonames.org) in plain
/// degrees, its name (else its region). The list is Resources/places.bin, packed by scripts/export_places.py from the
/// desktop's own copy; the GPS never leaves the phone.
public enum Places {
    final class Table: Sendable {
        let lat: [Double]
        let lon: [Double]
        let names: [Substring]

        init?(_ data: Data) {
            guard data.count >= 8, data.prefix(4) == Data("PPL1".utf8) else { return nil }
            let n = data.withUnsafeBytes { Int($0.loadUnaligned(fromByteOffset: 4, as: UInt32.self).littleEndian) }
            guard data.count >= 8 + 8 * n else { return nil }
            var la = [Double](repeating: 0, count: n), lo = [Double](repeating: 0, count: n)
            data.withUnsafeBytes { raw in
                for i in 0..<n {
                    la[i] = Double(Int32(littleEndian: raw.loadUnaligned(fromByteOffset: 8 + 4 * i, as: Int32.self))) / 100000.0
                    lo[i] = Double(Int32(littleEndian: raw.loadUnaligned(fromByteOffset: 8 + 4 * n + 4 * i, as: Int32.self))) / 100000.0
                }
            }
            let text = String(decoding: data.suffix(from: data.startIndex + 8 + 8 * n), as: UTF8.self)
            let names = text.split(separator: "\n", omittingEmptySubsequences: false)
            guard names.count == n else { return nil }
            lat = la
            lon = lo
            self.names = names
        }
    }

    static let table: Table? = Bundle.module.url(forResource: "places", withExtension: "bin")
        .flatMap { try? Data(contentsOf: $0, options: .mappedIfSafe) }
        .flatMap(Table.init)

    /// Whether the place list came with this build.
    public static var available: Bool { table != nil }

    /// The town nearest to (lat, lon), as the desktop names it; nil without the list or when the town has no name.
    public static func name(lat: Double, lon: Double) -> String? {
        guard let t = table, !t.lat.isEmpty else { return nil }
        var best = Double.infinity, at = -1
        t.lat.withUnsafeBufferPointer { la in
            t.lon.withUnsafeBufferPointer { lo in
                for i in 0..<la.count {
                    let a = lat - la[i], b = lon - lo[i]
                    let d = a * a + b * b
                    if d < best {
                        best = d
                        at = i
                    }
                }
            }
        }
        guard at >= 0 else { return nil }
        let n = String(t.names[at])
        return n.isEmpty ? nil : n
    }

    /// Great-circle distance in km (analyze/context.py `haversine_km`).
    public static func km(_ a: GeoPoint, _ b: GeoPoint) -> Double {
        let r = 6371.0, rad = Double.pi / 180
        let p1 = a.lat * rad, p2 = b.lat * rad
        let dp = p2 - p1, dl = (b.lon - a.lon) * rad
        let s1 = sin(dp / 2), s2 = sin(dl / 2)
        let h = s1 * s1 + cos(p1) * cos(p2) * s2 * s2
        return 2 * r * asin(h.squareRoot())
    }
}
