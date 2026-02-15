use criterion::{Criterion, criterion_group, criterion_main};
use std::hint::black_box;

fn parse_xml_benchmark(c: &mut Criterion) {
    c.bench_function("parse_small_xml", |b| {
        b.iter(|| {
            // Benchmark XML parsing performance
            // This would parse actual XML in a real benchmark
            let result = black_box(42);
            black_box(result);
        });
    });

    c.bench_function("calculate_hash", |b| {
        b.iter(|| {
            // Benchmark SHA256 calculation
            use sha2::{Digest, Sha256};
            let mut hasher = Sha256::new();
            hasher.update(b"test data");
            let result = hasher.finalize();
            black_box(result);
        });
    });
}

criterion_group!(benches, parse_xml_benchmark);
criterion_main!(benches);
