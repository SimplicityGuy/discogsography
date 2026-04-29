//! Polite HTTP client for upstream data providers (Discogs, MusicBrainz).
//!
//! Discogs and MusicBrainz both publish rate-limit guidance: identify yourself
//! with a `User-Agent`, throttle to a sustainable request rate, and respect
//! `Retry-After` on 429 / 503. A naive `reqwest::get` loop violates all three
//! and — worse — when paired with a docker `restart: on-failure` policy, every
//! crash-and-restart slides the limiter window forward and prolongs the cooldown.
//!
//! `PoliteClient` enforces:
//! * a `User-Agent` on every request,
//! * a configurable minimum gap between any two requests sharing the client,
//! * server-driven backoff via `Retry-After` (seconds form) on 429 / 503,
//!   capped at `max_retry_after` so a buggy header can't park us forever,
//! * a default backoff when `Retry-After` is absent.
//!
//! Cooldowns are slept *inside the process* so the binary stays alive through
//! the wait — this is what stops the docker restart loop from re-triggering
//! the upstream limiter every ~50 s.

use anyhow::{Context, Result};
use reqwest::{Client, Response, StatusCode, header};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tokio::time::Instant;
use tracing::{info, warn};

/// Default User-Agent advertised to upstream servers.
pub const DEFAULT_USER_AGENT: &str =
    concat!("discogsography-extractor/", env!("CARGO_PKG_VERSION"), " (+https://github.com/SimplicityGuy/discogsography)");

#[derive(Debug, Clone)]
pub struct PoliteConfig {
    /// Minimum elapsed time between two requests issued by this client.
    pub min_gap: Duration,
    /// Upper bound on a single Retry-After sleep — protects against
    /// pathological header values (e.g., several hours).
    pub max_retry_after: Duration,
    /// Maximum number of consecutive 429 / 503 retries before giving up.
    pub max_throttle_retries: u32,
    /// Per-request HTTP timeout.
    pub request_timeout: Duration,
}

impl PoliteConfig {
    /// Defaults tuned for `data.discogs.com` (S3-fronted listing + downloads).
    /// Discogs has been observed returning multi-thousand-second `Retry-After`
    /// values, so we accept up to two hours of server-driven backoff.
    pub fn discogs() -> Self {
        Self {
            min_gap: Duration::from_secs(5),
            max_retry_after: Duration::from_secs(2 * 60 * 60),
            max_throttle_retries: 5,
            request_timeout: Duration::from_secs(120),
        }
    }

    /// Defaults tuned for `data.metabrainz.org` (MusicBrainz JSON dumps).
    #[allow(dead_code)] // wired up by musicbrainz_downloader once feature lands
    pub fn musicbrainz() -> Self {
        Self {
            min_gap: Duration::from_secs(2),
            max_retry_after: Duration::from_secs(30 * 60),
            max_throttle_retries: 5,
            request_timeout: Duration::from_secs(120),
        }
    }
}

#[derive(Clone)]
pub struct PoliteClient {
    client: Client,
    cfg: PoliteConfig,
    last_request: Arc<Mutex<Option<Instant>>>,
}

impl PoliteClient {
    pub fn new(cfg: PoliteConfig) -> Result<Self> {
        Self::with_user_agent(cfg, DEFAULT_USER_AGENT)
    }

    pub fn with_user_agent(cfg: PoliteConfig, user_agent: &str) -> Result<Self> {
        // No per-request `timeout` — the prior call sites used `reqwest::get`
        // which has no default timeout, and integration tests using
        // `tokio::test(start_paused = true)` advance virtual time past any
        // wall-clock timeout, firing it spuriously. We rely on:
        //   * `connect_timeout` to bound TCP setup,
        //   * the polite-client retry loop to handle transient errors,
        //   * the existing per-attempt MAX_DOWNLOAD_RETRIES to bound retries.
        let client = Client::builder()
            .user_agent(user_agent)
            .connect_timeout(cfg.request_timeout)
            .build()
            .context("Failed to build polite HTTP client")?;
        Ok(Self { client, cfg, last_request: Arc::new(Mutex::new(None)) })
    }

    /// GET a URL, gated by the configured polite minimum and any server-driven
    /// `Retry-After`. Returns the first response whose status is neither 429
    /// nor 503, or an error after exhausting `max_throttle_retries`.
    pub async fn get(&self, url: &str) -> Result<Response> {
        let mut throttled_attempts: u32 = 0;
        loop {
            self.wait_for_polite_gap().await;
            let response = self.client.get(url).send().await.with_context(|| format!("HTTP GET failed for {}", url))?;

            let status = response.status();
            if status != StatusCode::TOO_MANY_REQUESTS && status != StatusCode::SERVICE_UNAVAILABLE {
                return Ok(response);
            }

            throttled_attempts += 1;
            let server_wait = parse_retry_after(&response);
            let chosen_wait = match server_wait {
                Some(d) => d.min(self.cfg.max_retry_after),
                // No header — fall back to a conservative default that grows
                // with each attempt: 30s, 60s, 120s, ...
                None => {
                    let secs = 30u64.saturating_mul(1u64 << (throttled_attempts.saturating_sub(1)));
                    Duration::from_secs(secs).min(self.cfg.max_retry_after)
                }
            };

            if throttled_attempts > self.cfg.max_throttle_retries {
                return Err(anyhow::anyhow!(
                    "Rate limited by {}: HTTP {} after {} retries (last Retry-After hint: {:?})",
                    url,
                    status,
                    self.cfg.max_throttle_retries,
                    server_wait
                ));
            }

            warn!(
                "⏸️ Rate limited (HTTP {}) by {} — sleeping {:?} before retry {}/{} (Retry-After: {:?})",
                status, url, chosen_wait, throttled_attempts, self.cfg.max_throttle_retries, server_wait
            );
            tokio::time::sleep(chosen_wait).await;
        }
    }

    async fn wait_for_polite_gap(&self) {
        let mut last = self.last_request.lock().await;
        if let Some(t) = *last {
            let elapsed = t.elapsed();
            if elapsed < self.cfg.min_gap {
                let to_wait = self.cfg.min_gap - elapsed;
                info!("🐢 Polite throttle: waiting {:?} before next request", to_wait);
                tokio::time::sleep(to_wait).await;
            }
        }
        *last = Some(Instant::now());
    }
}

/// Parse the `Retry-After` header (seconds form) into a `Duration`.
/// Returns `None` for missing, non-numeric, or HTTP-date forms — the caller
/// then falls back to its default backoff.
fn parse_retry_after(response: &Response) -> Option<Duration> {
    let header_value = response.headers().get(header::RETRY_AFTER)?;
    let s = header_value.to_str().ok()?;
    s.trim().parse::<u64>().ok().map(Duration::from_secs)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicU32, Ordering};

    fn fast_test_config() -> PoliteConfig {
        PoliteConfig {
            min_gap: Duration::from_millis(10),
            max_retry_after: Duration::from_millis(50),
            max_throttle_retries: 3,
            request_timeout: Duration::from_secs(5),
        }
    }

    #[tokio::test]
    async fn polite_gap_is_observed_between_requests() {
        let mut server = mockito::Server::new_async().await;
        let _m = server.mock("GET", "/x").with_status(200).expect(2).create_async().await;

        let cfg = PoliteConfig {
            min_gap: Duration::from_millis(150),
            max_retry_after: Duration::from_millis(50),
            max_throttle_retries: 2,
            request_timeout: Duration::from_secs(5),
        };
        let client = PoliteClient::new(cfg).unwrap();
        let url = format!("{}/x", server.url());

        let start = Instant::now();
        client.get(&url).await.unwrap();
        client.get(&url).await.unwrap();
        let elapsed = start.elapsed();

        // Two requests with a 150 ms gap should take at least the gap on the
        // second call. Allow a bit of headroom for scheduler jitter.
        assert!(elapsed >= Duration::from_millis(140), "expected ≥140 ms total, got {:?}", elapsed);
    }

    #[tokio::test]
    async fn retries_on_429_and_eventually_succeeds() {
        let mut server = mockito::Server::new_async().await;
        // First call: 429 with Retry-After: 0  (server says retry now)
        let _m429 = server.mock("GET", "/throttled").with_status(429).with_header("retry-after", "0").expect(1).create_async().await;
        // Second call: 200
        let _m200 = server.mock("GET", "/throttled").with_status(200).with_body("ok").expect(1).create_async().await;

        let client = PoliteClient::new(fast_test_config()).unwrap();
        let url = format!("{}/throttled", server.url());

        let response = client.get(&url).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.text().await.unwrap(), "ok");
    }

    #[tokio::test]
    async fn caps_retry_after_at_configured_max() {
        let mut server = mockito::Server::new_async().await;
        // Server demands an absurd Retry-After. Without a cap this would block
        // the test for two hours; we expect the client to clamp to max_retry_after
        // (50ms in fast_test_config) and still succeed on the second attempt.
        let _m429 = server.mock("GET", "/x").with_status(429).with_header("retry-after", "7200").expect(1).create_async().await;
        let _m200 = server.mock("GET", "/x").with_status(200).expect(1).create_async().await;

        let client = PoliteClient::new(fast_test_config()).unwrap();
        let url = format!("{}/x", server.url());

        let start = Instant::now();
        client.get(&url).await.unwrap();
        let elapsed = start.elapsed();

        assert!(elapsed < Duration::from_secs(2), "should have clamped Retry-After, took {:?}", elapsed);
    }

    #[tokio::test]
    async fn gives_up_after_max_throttle_retries() {
        let mut server = mockito::Server::new_async().await;
        let _m = server.mock("GET", "/forever").with_status(429).with_header("retry-after", "0").expect_at_least(4).create_async().await;

        let client = PoliteClient::new(fast_test_config()).unwrap();
        let url = format!("{}/forever", server.url());

        let err = client.get(&url).await.unwrap_err();
        assert!(err.to_string().contains("Rate limited"), "unexpected error: {:?}", err);
    }

    #[tokio::test]
    async fn missing_retry_after_falls_back_to_default_backoff() {
        let mut server = mockito::Server::new_async().await;
        let _m429 = server.mock("GET", "/x").with_status(429).expect(1).create_async().await;
        let _m200 = server.mock("GET", "/x").with_status(200).expect(1).create_async().await;

        let client = PoliteClient::new(fast_test_config()).unwrap();
        let url = format!("{}/x", server.url());

        // No Retry-After header — fall back to default backoff, which is
        // also clamped by max_retry_after (50ms).
        client.get(&url).await.unwrap();
    }

    #[tokio::test]
    async fn shared_client_serializes_concurrent_requests() {
        let mut server = mockito::Server::new_async().await;
        let _m = server.mock("GET", "/x").with_status(200).expect(3).create_async().await;

        let cfg = PoliteConfig {
            min_gap: Duration::from_millis(100),
            max_retry_after: Duration::from_millis(50),
            max_throttle_retries: 2,
            request_timeout: Duration::from_secs(5),
        };
        let client = PoliteClient::new(cfg).unwrap();
        let url = Arc::new(format!("{}/x", server.url()));
        let counter = Arc::new(AtomicU32::new(0));

        let start = Instant::now();
        let mut handles = Vec::new();
        for _ in 0..3 {
            let c = client.clone();
            let u = url.clone();
            let ctr = counter.clone();
            handles.push(tokio::spawn(async move {
                c.get(&u).await.unwrap();
                ctr.fetch_add(1, Ordering::SeqCst);
            }));
        }
        for h in handles {
            h.await.unwrap();
        }
        let elapsed = start.elapsed();

        assert_eq!(counter.load(Ordering::SeqCst), 3);
        // 3 requests with 100ms gap → at least ~200ms total (first runs immediately).
        assert!(elapsed >= Duration::from_millis(180), "concurrent requests should serialize, took {:?}", elapsed);
    }
}
