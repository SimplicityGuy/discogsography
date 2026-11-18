use extractor::state_marker::StateMarker;
use extractor::types::{ExtractionCompleteMessage, FileCompleteMessage};
use serde_json::json;

#[test]
fn completion_messages_retain_the_existing_json_timestamp_contract() {
    let file_json = json!({
        "data_type": "artists",
        "timestamp": "2026-11-17T23:59:59.123456700Z",
        "total_processed": 42,
        "file": "discogs_20261101_artists.xml.gz",
    });
    let file: FileCompleteMessage = serde_json::from_value(file_json.clone()).unwrap();
    assert_eq!(serde_json::to_value(file).unwrap(), file_json);

    let complete_json = json!({
        "version": "20261101",
        "timestamp": "2026-11-18T00:00:01.120Z",
        "started_at": "2026-11-17T23:59:59.123400Z",
        "record_counts": {"artists": 42},
    });
    let complete: ExtractionCompleteMessage = serde_json::from_value(complete_json.clone()).unwrap();
    assert_eq!(serde_json::to_value(complete).unwrap(), complete_json);
}

#[tokio::test]
async fn historical_marker_loads_missing_and_null_timestamps_and_retains_resume_time() {
    // A pre-migration marker, including optional timestamps absent from older files.
    let marker_json = json!({
        "metadata_version": "1.0",
        "last_updated": "2026-11-18T00:00:01.123456700Z",
        "current_version": "20261101",
        "download_phase": {
            "status": "completed", "started_at": "2026-11-17T23:59:59.100Z", "completed_at": null,
            "files_downloaded": 1, "files_total": 1, "bytes_downloaded": 10,
            "downloads_by_file": {"artists.xml.gz": {"status": "completed", "bytes_downloaded": 10}},
            "errors": [],
        },
        "processing_phase": {
            "status": "in_progress", "started_at": "2026-11-18T00:59:59.123400+01:00",
            "completed_at": "2026-11-18T00:00:01Z",
            "files_processed": 1, "files_total": 1, "records_extracted": 42, "current_file": null,
            "progress_by_file": {
                "artists.xml.gz": {"status": "completed", "records_extracted": 42, "messages_published": 42, "batches_sent": 1},
            },
            "errors": [],
        },
        "publishing_phase": {"status": "in_progress", "messages_published": 42, "batches_sent": 1, "errors": []},
        "summary": {"overall_status": "in_progress", "total_duration_seconds": null, "files_by_type": {}},
    });
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join(".extraction_status_20261101.json");
    tokio::fs::write(&path, serde_json::to_vec(&marker_json).unwrap()).await.unwrap();
    let mut marker = StateMarker::load(&path).await.unwrap().expect("historical marker must resume");
    assert!(marker.download_phase.completed_at.is_none());
    assert!(marker.download_phase.downloads_by_file["artists.xml.gz"].started_at.is_none());
    assert!(marker.processing_phase.progress_by_file["artists.xml.gz"].completed_at.is_none());
    assert!(marker.publishing_phase.last_amqp_heartbeat.is_none());

    let serialized = serde_json::to_value(&marker).unwrap();
    assert_eq!(serialized["last_updated"], marker_json["last_updated"]);
    assert_eq!(serialized["processing_phase"]["started_at"], "2026-11-17T23:59:59.123400Z");

    let started_at = marker.processing_phase.started_at;
    // The extractor's resume branch refreshes the total without restarting the phase.
    marker.processing_phase.files_total = 1;
    assert_eq!(marker.processing_phase.started_at, started_at);
    marker.complete_extraction();
    assert_eq!(marker.summary.total_duration_seconds, Some(1.0));
}
