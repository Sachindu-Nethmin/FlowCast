import Foundation
import Observation
import Security

/// Values for the configurables docs pages ask for — API keys, tokens, tenant
/// URLs — shared across pages by name, so a HubSpot token entered once serves
/// every HubSpot page.
///
/// Secrets live in the login Keychain, plain values in UserDefaults. Neither is
/// written to a workflow file or a log: they reach tools/write_config.py through
/// the recording process's environment, and it writes them to the project's
/// Config.toml — off camera, never typed into the UI.
@Observable
final class InputStore {
    private let service = "dev.flowcast.studio.inputs"
    private let d = UserDefaults.standard
    private(set) var revision = 0

    private var plain: [String: String] {
        get { d.dictionary(forKey: "inputValues") as? [String: String] ?? [:] }
        set { d.set(newValue, forKey: "inputValues") }
    }
    private var secretNames: [String] {
        get { d.stringArray(forKey: "secretInputNames") ?? [] }
        set { d.set(Array(Set(newValue)).sorted(), forKey: "secretInputNames") }
    }

    func value(_ name: String, secret: Bool) -> String? {
        _ = revision
        return secret ? keychainRead(name) : plain[name]
    }

    func has(_ input: DocInput) -> Bool {
        !(value(input.name, secret: input.secret) ?? "").isEmpty
    }

    func set(_ name: String, _ value: String, secret: Bool) {
        let v = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if v.isEmpty { remove(name); return }
        if secret {
            keychainWrite(name, v)
            secretNames += [name]
        } else {
            var p = plain
            p[name] = v
            plain = p
        }
        revision += 1
    }

    func remove(_ name: String) {
        keychainDelete(name)
        secretNames = secretNames.filter { $0 != name }
        var p = plain
        p[name] = nil
        plain = p
        revision += 1
    }

    /// Everything saved, for Settings › Keys.
    var saved: [(name: String, secret: Bool)] {
        _ = revision
        return (plain.keys.map { ($0, false) } + secretNames.map { ($0, true) })
            .sorted { $0.0.lowercased() < $1.0.lowercased() }
    }

    /// Inputs a page needs that neither you nor a started prerequisite has given.
    func missing(for page: DocPage) -> [DocInput] {
        page.inputs.filter { $0.auto == nil && !has($0) }
    }

    /// What the recording process needs: your values (as JSON, never argv) and
    /// which prerequisites are running, so write_config can fill the rest.
    func environment(for page: DocPage) -> [String: String] {
        var values: [String: String] = [:]
        for i in page.inputs {
            if let v = value(i.name, secret: i.secret), !v.isEmpty { values[i.name] = v }
        }
        let json = (try? JSONSerialization.data(withJSONObject: values)).flatMap {
            String(data: $0, encoding: .utf8)
        } ?? "{}"
        var env = ["FLOWCAST_INPUTS": json, "FLOWCAST_RECIPES": page.recipes.joined(separator: ",")]
        // Keys and account details never appear in a video or its guide: the
        // recording shows placeholders, and yours (when entered) are written
        // in off camera just before the run step (tools/autopilot.py).
        if page.inputs.contains(where: { $0.auto == nil }) { env["FLOWCAST_PLACEHOLDERS"] = "1" }
        return env
    }

    // ── Keychain ──────────────────────────────────────────────────────────────

    private func query(_ name: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: name]
    }

    private func keychainRead(_ name: String) -> String? {
        var q = query(name)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func keychainWrite(_ name: String, _ value: String) {
        let data = Data(value.utf8)
        let status = SecItemUpdate(query(name) as CFDictionary,
                                   [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var q = query(name)
            q[kSecValueData as String] = data
            q[kSecAttrLabel as String] = "FlowCast Studio — \(name)"
            q[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlocked
            SecItemAdd(q as CFDictionary, nil)
        }
    }

    private func keychainDelete(_ name: String) {
        SecItemDelete(query(name) as CFDictionary)
    }
}
