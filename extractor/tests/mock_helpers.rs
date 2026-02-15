//! Mock helpers for testing async I/O operations

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

/// Type alias for published messages storage
type PublishedMessages = Arc<Mutex<Vec<(String, Vec<u8>)>>>;

/// Mock message queue for testing
#[derive(Clone)]
pub struct MockMessageQueue {
    pub published_messages: PublishedMessages,
    pub should_fail: Arc<Mutex<bool>>,
}

impl Default for MockMessageQueue {
    fn default() -> Self {
        Self::new()
    }
}

impl MockMessageQueue {
    pub fn new() -> Self {
        Self {
            published_messages: Arc::new(Mutex::new(Vec::new())),
            should_fail: Arc::new(Mutex::new(false)),
        }
    }

    pub fn set_should_fail(&self, should_fail: bool) {
        *self.should_fail.lock().unwrap() = should_fail;
    }

    pub fn get_published_messages(&self) -> Vec<(String, Vec<u8>)> {
        self.published_messages.lock().unwrap().clone()
    }

    pub async fn publish(&self, routing_key: &str, payload: Vec<u8>) -> anyhow::Result<()> {
        if *self.should_fail.lock().unwrap() {
            return Err(anyhow::anyhow!("Mock failure"));
        }

        self.published_messages
            .lock()
            .unwrap()
            .push((routing_key.to_string(), payload));

        Ok(())
    }
}

/// Mock downloader for testing
pub struct MockDownloader {
    pub files: Arc<Mutex<HashMap<String, Vec<u8>>>>,
}

impl Default for MockDownloader {
    fn default() -> Self {
        Self::new()
    }
}

impl MockDownloader {
    pub fn new() -> Self {
        Self {
            files: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub fn add_file(&self, path: &str, content: Vec<u8>) {
        self.files.lock().unwrap().insert(path.to_string(), content);
    }

    pub async fn download(&self, path: &str) -> anyhow::Result<Vec<u8>> {
        self.files
            .lock()
            .unwrap()
            .get(path)
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("File not found"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_mock_message_queue() {
        let mq = MockMessageQueue::new();

        mq.publish("test.route", b"test message".to_vec()).await.unwrap();

        let messages = mq.get_published_messages();
        assert_eq!(messages.len(), 1);
        assert_eq!(messages[0].0, "test.route");
        assert_eq!(messages[0].1, b"test message");
    }

    #[tokio::test]
    async fn test_mock_message_queue_failure() {
        let mq = MockMessageQueue::new();
        mq.set_should_fail(true);

        let result = mq.publish("test.route", b"test".to_vec()).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_mock_downloader() {
        let downloader = MockDownloader::new();
        downloader.add_file("test.xml", b"<xml>test</xml>".to_vec());

        let content = downloader.download("test.xml").await.unwrap();
        assert_eq!(content, b"<xml>test</xml>");
    }

    #[tokio::test]
    async fn test_mock_downloader_not_found() {
        let downloader = MockDownloader::new();

        let result = downloader.download("nonexistent.xml").await;
        assert!(result.is_err());
    }
}
