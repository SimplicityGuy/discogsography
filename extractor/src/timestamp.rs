//! UTC timestamps at the extractor's persisted-marker and AMQP boundaries.
//!
//! Keep the existing string representation independent of the datetime library:
//! JSON uses `Z`, explicit RFC 3339 strings use `+00:00`, and fractional seconds
//! retain the previous 0/3/6/9 digit precision without losing nanoseconds.

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::str::FromStr;
use time::format_description::well_known::Rfc3339;
use time::{OffsetDateTime, UtcOffset};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UtcTimestamp(OffsetDateTime);

impl UtcTimestamp {
    pub fn now() -> Self {
        Self(OffsetDateTime::now_utc())
    }

    pub fn to_rfc3339(self) -> String {
        self.format_timestamp("+00:00")
    }

    pub fn compact_month(self) -> String {
        format!("{:04}{:02}", self.0.year(), u8::from(self.0.month()))
    }

    pub fn compact_date(self) -> String {
        format!("{}{:02}", self.compact_month(), self.0.day())
    }

    /// Elapsed whole seconds, truncated toward zero as in existing extraction summaries.
    pub fn whole_seconds_since(self, earlier: Self) -> i64 {
        (self.0 - earlier.0).whole_seconds()
    }

    fn format_timestamp(self, suffix: &str) -> String {
        let year = self.0.year();
        let year = if (0..=9999).contains(&year) {
            format!("{year:04}")
        } else {
            format!("{year:+05}")
        };
        let date_time =
            format!("{year}-{:02}-{:02}T{:02}:{:02}:{:02}", u8::from(self.0.month()), self.0.day(), self.0.hour(), self.0.minute(), self.0.second(),);
        let nanos = self.0.nanosecond();
        let fraction = if nanos == 0 {
            String::new()
        } else if nanos.is_multiple_of(1_000_000) {
            format!(".{:03}", nanos / 1_000_000)
        } else if nanos.is_multiple_of(1_000) {
            format!(".{:06}", nanos / 1_000)
        } else {
            format!(".{nanos:09}")
        };
        format!("{date_time}{fraction}{suffix}")
    }
}

impl FromStr for UtcTimestamp {
    type Err = time::error::Parse;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        OffsetDateTime::parse(value, &Rfc3339).map(|value| Self(value.to_offset(UtcOffset::UTC)))
    }
}

impl Serialize for UtcTimestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.format_timestamp("Z"))
    }
}

impl<'de> Deserialize<'de> for UtcTimestamp {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        String::deserialize(deserializer)?.parse().map_err(serde::de::Error::custom)
    }
}

#[cfg(test)]
mod tests {
    use super::UtcTimestamp;

    #[test]
    fn historical_json_precision_and_rfc3339_offset_are_preserved() {
        for fraction in ["", ".120", ".123400", ".123456700", ".000000001"] {
            let json = format!("\"2026-11-17T23:59:59{fraction}Z\"");
            let timestamp: UtcTimestamp = serde_json::from_str(&json).unwrap();
            assert_eq!(serde_json::to_string(&timestamp).unwrap(), json);
            assert_eq!(timestamp.to_rfc3339(), format!("2026-11-17T23:59:59{fraction}+00:00"));
        }
        let short_fraction: UtcTimestamp = "2026-11-17T23:59:59.1Z".parse().unwrap();
        assert_eq!(serde_json::to_string(&short_fraction).unwrap(), "\"2026-11-17T23:59:59.100Z\"");
        assert_eq!(short_fraction.to_rfc3339(), "2026-11-17T23:59:59.100+00:00");
    }

    #[test]
    fn offsets_normalize_to_utc_without_losing_fractional_precision() {
        let timestamp: UtcTimestamp = "2026-12-01T00:30:00.123456789+01:00".parse().unwrap();
        assert_eq!(serde_json::to_string(&timestamp).unwrap(), "\"2026-11-30T23:30:00.123456789Z\"");
        assert_eq!(timestamp, "2026-11-30T23:30:00.123456789+00:00".parse().unwrap());
    }

    #[test]
    fn compact_dates_use_the_utc_day_and_month() {
        let timestamp: UtcTimestamp = "2027-01-01T00:30:00+01:00".parse().unwrap();
        assert_eq!(timestamp.compact_month(), "202612");
        assert_eq!(timestamp.compact_date(), "20261231");
        let leap_day: UtcTimestamp = "2024-03-01T00:30:00+01:00".parse().unwrap();
        assert_eq!(leap_day.compact_date(), "20240229");
    }

    #[test]
    fn durations_truncate_fractional_seconds_toward_zero() {
        let start: UtcTimestamp = "2026-11-17T23:59:59.100Z".parse().unwrap();
        let end: UtcTimestamp = "2026-11-18T00:00:01Z".parse().unwrap();
        assert_eq!(end.whole_seconds_since(start), 1);
        assert_eq!(start.whole_seconds_since(end), -1);
    }
}
