import ApelinProtocol
import Foundation

extension Notification.Name {
    static let enabledModelsChanged = Notification.Name("wiki.qaq.apelin.enabledModelsChanged")
}

/// A device preference, separate from the provider's credentials and catalog.
enum EnabledModels {
    private static func key(_ provider: AgentProvider) -> String {
        "enabledModels.\(provider.rawValue)"
    }

    static func ids(for provider: AgentProvider) -> Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: key(provider)) ?? [])
    }

    static func save(_ models: Set<String>, custom: Set<String>, hidden: Set<String>, for provider: AgentProvider) {
        UserDefaults.standard.set(models.sorted(), forKey: key(provider))
        UserDefaults.standard.set(custom.sorted(), forKey: "customModels.\(provider.rawValue)")
        UserDefaults.standard.set(hidden.sorted(), forKey: "hiddenModels.\(provider.rawValue)")
        NotificationCenter.default.post(name: .enabledModelsChanged, object: nil)
    }

    static func remove(for provider: AgentProvider) {
        UserDefaults.standard.removeObject(forKey: key(provider))
        UserDefaults.standard.removeObject(forKey: "customModels.\(provider.rawValue)")
        UserDefaults.standard.removeObject(forKey: "hiddenModels.\(provider.rawValue)")
        NotificationCenter.default.post(name: .enabledModelsChanged, object: nil)
    }

    static func customIDs(for provider: AgentProvider) -> [String] {
        UserDefaults.standard.stringArray(forKey: "customModels.\(provider.rawValue)") ?? []
    }

    static func hiddenIDs(for provider: AgentProvider) -> Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: "hiddenModels.\(provider.rawValue)") ?? [])
    }

    /// The models of `account` the reader has enabled, as the chat panel
    /// offers them: an API-key account's are the ids it enabled, a
    /// subscription's are the ones its catalog lists and the reader enabled.
    static func enabled(in account: AgentAccount) -> [String] {
        let ids = ids(for: account.provider).subtracting(hiddenIDs(for: account.provider))
        return account.isAPIKeyAccount
            ? ids.sorted()
            : (account.models ?? []).filter { ids.contains($0) }
    }

    /// Whether the chat panel offers `model` of `account`.
    static func isEnabled(_ model: String, in account: AgentAccount) -> Bool {
        ids(for: account.provider).subtracting(hiddenIDs(for: account.provider)).contains(model)
    }

    /// Turns `model` of `account` on or off without touching any other id,
    /// the custom ids or the hidden ones; a model turned back on stops being
    /// hidden. Answers whether it is enabled now.
    @discardableResult
    static func setEnabled(_ enabled: Bool, _ model: String, in account: AgentAccount) -> Bool {
        var ids = ids(for: account.provider)
        var hidden = hiddenIDs(for: account.provider)
        if enabled {
            ids.insert(model)
            hidden.remove(model)
        } else {
            ids.remove(model)
        }
        save(
            ids,
            custom: Set(customIDs(for: account.provider)),
            hidden: hidden,
            for: account.provider,
        )
        return enabled
    }

    static func accounts(from accounts: [AgentAccount]) -> [AgentAccount] {
        accounts.compactMap { account in
            guard account.signedIn else { return nil }
            let models = enabled(in: account)
            guard !models.isEmpty else { return nil }
            var shown = account
            shown.models = models
            return shown
        }
    }
}
