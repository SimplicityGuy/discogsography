// Library exports for testing

pub mod config;
pub mod discogs_downloader;
pub mod extractor;
pub mod health;
pub mod jsonl_parser;
pub mod message_queue;
pub mod musicbrainz_downloader;
pub mod normalize;
pub mod parser;
pub mod polite_http;
pub mod rules;
pub mod state_marker;
pub mod types;

// Additional test modules
#[cfg(test)]
#[path = "tests/message_queue_unit_tests.rs"]
mod message_queue_unit_tests;
