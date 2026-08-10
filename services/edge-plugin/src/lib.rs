//! AICO edge plugin (Proxy-Wasm Service Extension) detection logic.
//!
//! On each request: if the User-Agent is an AI crawler (and not a loop), rewrite the
//! request `:path` to `${ai_path_prefix}/<original>`. The URL map then
//! path-routes `${ai_path_prefix}/*` to the optimized backend (the serving shim).
//! Non-matching (human) traffic is untouched. Operates purely on User-Agent without source IP or ASN logic.
//!
//! The bot list and path prefix are configured via JSON plugin config
//! and can be updated without rebuilding. The decision logic (`decide_rewrite`) is host-testable.

use serde::Deserialize;

/// Loop-guard 2: worker offline crawler UA marker (`AIContentOptimizer/1.0 …`).
const OUR_CRAWLER_MARKER: &str = "aicontentoptimizer";

/// Default include-list (lowercased UA substrings) if no plugin config is supplied.
/// Policy: AI assistants, agents, answer engines, and training crawlers. Excludes
/// AI Search Crawlers (Applebot, Amzn-SearchBot, etc.) because routing search crawlers to
/// different content risks cloaking and search ranking issues. Tune via plugin config.
const DEFAULT_TOKENS: &[&str] = &[
    "gptbot", "chatgpt-user", "oai-searchbot", "chatgpt agent",
    "claudebot", "claude-user", "anthropic-ai",
    "perplexitybot", "perplexity-user",
    "google-extended", "gemini-deep-research", "google-notebooklm",
    "ccbot", "bytespider", "amazonbot", "amzn-user", "meta-externalagent",
    "duckassistbot", "kimi-user", "mistralai-user", "cohere-ai", "deepseekbot",
    "youbot", "iaskspider", "petalbot",
];

#[derive(Deserialize, Clone)]
#[serde(default)]
pub struct Config {
    pub ai_path_prefix: String,
    pub ai_bot_user_agents: Vec<String>,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            ai_path_prefix: "/_ai_optimized".to_string(),
            ai_bot_user_agents: DEFAULT_TOKENS.iter().map(|s| s.to_string()).collect(),
        }
    }
}

/// Pure routing decision. Returns `Some(new_path)` to rewrite, or `None` to leave the
/// request untouched. Host-testable (no Proxy-Wasm host calls).
pub fn decide_rewrite(
    user_agent: &str,
    path: &str,
    has_loop_guard_header: bool,
    cfg: &Config,
) -> Option<String> {
    if has_loop_guard_header {
        return None; // loop-guard 1: the shim's origin proxy
    }
    let ua = user_agent.to_lowercase();
    if ua.contains(OUR_CRAWLER_MARKER) {
        return None; // loop-guard 2: worker crawler
    }
    if !cfg.ai_bot_user_agents.iter().any(|t| ua.contains(&t.to_lowercase())) {
        return None; // human / other → untouched
    }
    if path.starts_with(&cfg.ai_path_prefix) {
        return None; // already rewritten
    }
    Some(format!("{}{}", cfg.ai_path_prefix, path))
}

// --- Proxy-Wasm host glue (wasm target only) --------------------------------
#[cfg(target_arch = "wasm32")]
mod plugin {
    use super::{decide_rewrite, Config};
    use proxy_wasm::traits::{Context, HttpContext, RootContext};
    use proxy_wasm::types::{Action, ContextType, LogLevel};
    use std::rc::Rc;

    const LOOP_GUARD_HEADER: &str = "x-from-llm-optimizer";

    proxy_wasm::main! {{
        proxy_wasm::set_log_level(LogLevel::Info);
        proxy_wasm::set_root_context(
            |_| -> Box<dyn RootContext> { Box::new(EdgeRoot { config: Rc::new(Config::default()) }) },
        );
    }}

    struct EdgeRoot {
        config: Rc<Config>,
    }
    impl Context for EdgeRoot {}
    impl RootContext for EdgeRoot {
        fn on_configure(&mut self, _n: usize) -> bool {
            if let Some(bytes) = self.get_plugin_configuration() {
                match serde_json::from_slice::<Config>(&bytes) {
                    Ok(c) => {
                        let _ = proxy_wasm::hostcalls::log(
                            LogLevel::Info,
                            &format!("aico: config loaded ({} tokens, prefix {})",
                                     c.ai_bot_user_agents.len(), c.ai_path_prefix),
                        );
                        self.config = Rc::new(c);
                    }
                    Err(e) => {
                        let _ = proxy_wasm::hostcalls::log(
                            LogLevel::Warn,
                            &format!("aico: bad plugin config ({e}); using defaults"),
                        );
                    }
                }
            }
            true
        }
        fn get_type(&self) -> Option<ContextType> {
            Some(ContextType::HttpContext)
        }
        fn create_http_context(&self, _id: u32) -> Option<Box<dyn HttpContext>> {
            Some(Box::new(EdgeHttp { config: self.config.clone() }))
        }
    }

    struct EdgeHttp {
        config: Rc<Config>,
    }
    impl Context for EdgeHttp {}
    impl HttpContext for EdgeHttp {
        fn on_http_request_headers(&mut self, _n: usize, _eos: bool) -> Action {
            let has_guard = self.get_http_request_header(LOOP_GUARD_HEADER).is_some();
            let ua = self.get_http_request_header("user-agent").unwrap_or_default();
            let path = self
                .get_http_request_header(":path")
                .unwrap_or_else(|| "/".to_string());
            if let Some(new_path) = decide_rewrite(&ua, &path, has_guard, &self.config) {
                self.set_http_request_header(":path", Some(&new_path));
                let _ = proxy_wasm::hostcalls::log(
                    LogLevel::Info,
                    &format!("aico: AI bot matched; rewrote {path} -> {new_path}"),
                );
            }
            Action::Continue
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{decide_rewrite, Config};

    const GPTBOT: &str = "Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)";
    const BROWSER: &str = "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36";

    fn cfg() -> Config {
        Config::default()
    }

    #[test]
    fn browser_is_untouched() {
        assert_eq!(decide_rewrite(BROWSER, "/p", false, &cfg()), None);
    }

    #[test]
    fn ai_bot_is_rewritten() {
        assert_eq!(
            decide_rewrite(GPTBOT, "/blog/x", false, &cfg()),
            Some("/_ai_optimized/blog/x".to_string())
        );
    }

    #[test]
    fn loop_guard_header_blocks_rewrite() {
        assert_eq!(decide_rewrite(GPTBOT, "/p", true, &cfg()), None);
    }

    #[test]
    fn our_own_crawler_is_untouched() {
        let ua = "AIContentOptimizer/1.0 (GCP Cloud CDN content optimizer)";
        assert_eq!(decide_rewrite(ua, "/p", false, &cfg()), None);
    }

    #[test]
    fn already_prefixed_is_not_double_rewritten() {
        assert_eq!(decide_rewrite(GPTBOT, "/_ai_optimized/p", false, &cfg()), None);
    }

    #[test]
    fn seo_search_crawler_is_excluded_by_default() {
        // Applebot (an AI Search Crawler) must not be routed due to cloaking risk.
        let applebot = "Mozilla/5.0 (compatible; Applebot/0.1; +http://www.apple.com/go/applebot)";
        assert_eq!(decide_rewrite(applebot, "/p", false, &cfg()), None);
    }

    #[test]
    fn config_json_overrides_defaults() {
        let c: Config =
            serde_json::from_str(r#"{"ai_path_prefix":"/opt","ai_bot_user_agents":["foobot"]}"#)
                .unwrap();
        assert_eq!(c.ai_path_prefix, "/opt");
        assert_eq!(
            decide_rewrite("hello FooBot/2.0 world", "/p", false, &c),
            Some("/opt/p".to_string())
        );
        // a default bot is no longer matched under the overriding config
        assert_eq!(decide_rewrite(GPTBOT, "/p", false, &c), None);
    }

    #[test]
    fn partial_config_falls_back_to_defaults_via_serde_default() {
        // only the prefix supplied; the bot list defaults
        let c: Config = serde_json::from_str(r#"{"ai_path_prefix":"/x"}"#).unwrap();
        assert_eq!(
            decide_rewrite(GPTBOT, "/p", false, &c),
            Some("/x/p".to_string())
        );
    }
}
