import Foundation

/// Any JSON value: the free-form parts of PrePro's files (a suggestion's payload, a timeline's meta, a playbook's
/// music block). Encodes back to exactly the same JSON.
public enum JSONValue: Codable, Equatable, Sendable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let b = try? c.decode(Bool.self) { self = .bool(b); return }
        if let n = try? c.decode(Double.self) { self = .number(n); return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        if let a = try? c.decode([JSONValue].self) { self = .array(a); return }
        if let o = try? c.decode([String: JSONValue].self) { self = .object(o); return }
        throw DecodingError.dataCorruptedError(in: c, debugDescription: "not a JSON value")
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let b): try c.encode(b)
        case .number(let n): try c.encode(n)
        case .string(let s): try c.encode(s)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }

    public var string: String? { if case .string(let s) = self { return s }; return nil }
    public var number: Double? { if case .number(let n) = self { return n }; return nil }
    public var bool: Bool? { if case .bool(let b) = self { return b }; return nil }
    public var array: [JSONValue]? { if case .array(let a) = self { return a }; return nil }
    public var object: [String: JSONValue]? { if case .object(let o) = self { return o }; return nil }
}

extension JSONValue {
    /// Any Codable value as plain JSON values (what pydantic's model_dump gives on the desktop). A missing optional is
    /// left out rather than written as null.
    public static func of<T: Encodable>(_ value: T) -> JSONValue {
        (try? PreProJSON.decoder().decode(JSONValue.self, from: PreProJSON.encoder().encode(value))) ?? .null
    }

    /// The same value with every null (and every key holding one) removed: how a file written with explicit nulls
    /// compares with one that leaves them out.
    public var withoutNulls: JSONValue {
        switch self {
        case .array(let a): return .array(a.filter { $0 != .null }.map(\.withoutNulls))
        case .object(let o): return .object(o.filter { $0.value != .null }.mapValues(\.withoutNulls))
        default: return self
        }
    }
}

extension KeyedDecodingContainer {
    /// The value, or the desktop schema's default when the key is missing or null (pydantic defaults).
    func v<T: Decodable>(_ key: Key, _ fallback: T) throws -> T {
        try decodeIfPresent(T.self, forKey: key) ?? fallback
    }
}

/// PrePro's JSON files: what the desktop engine writes, what the phone writes back.
public enum PreProJSON {
    public static func decoder() -> JSONDecoder { JSONDecoder() }

    public static func encoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.outputFormatting = [.sortedKeys]
        return e
    }
}
