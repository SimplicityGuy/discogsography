# `groovemap-music/catalog-ingestion` extraction evidence

Date: 2026-08-27

Destination: <https://github.com/groovemap-music/catalog-ingestion>

Visibility: private

## Boundary and history

The extraction used a disposable clone of the migration branch
`wt/bead/issue/discogsography-2kpm.10` at
`e5b83fd5e56a2dfd00089b307fe6f2bd5904c245`. `git filter-repo` retained
`extractor/`, the root `Cargo.lock` and `LICENSE`, the state-marker design, and the
extractor-owned Dockerfile test. It promoted the component and its repository test to the
destination root. The exact, reproducible command is committed in the destination's
`docs/extraction.md`.

The filter retained 292 relevant commits. Three destination commits established the
standalone repository and corrected the credential-free CI bootstrap, for 295 commits
total at `e7038d1492da54e91444bfa990598e8963972ce2`. No tags were copied or created.
The original monorepo `main` remains clean and unchanged at
`204f49e2429f074546dfc67e6354be2529a983ac`.

The current tree is MIT licensed by owner decision. Earlier revisions retain the license
text that applied to them, and generated third-party notices preserve dependency
attribution.

## Repository contract

- `catalog-ingestion` independently versions the Discogs and MusicBrainz ingestion unit;
- the Cargo package and deployed binary retain the compatibility name `extractor`;
- this repository owns catalog-event schemas, generated Rust and distributable Python
  bindings, fixtures, extraction rules, and producer compatibility policy;
- contract generation writes only inside this repository and never modifies consumers;
- consumers must pin an immutable repository commit or released contract artifact rather
  than using cross-repository relative paths;
- Rust 1.98.0, just 1.57.0, uv 0.12.5, Python 3.14.5, gitleaks 8.30.1,
  cargo-audit 0.22.2, cargo-cyclonedx 0.5.9, and cargo-deny 0.20.2 are pinned;
- both Docker base images are pinned by digest and the image runs as UID/GID 1000;
- CI dependencies use immutable action SHAs;
- the release workflow builds checksums, an SBOM, and notices but does not publish an
  image, package, tag, release, or other artifact.

## Verification

- `just check`: passed, including format, Clippy, every unit/integration suite, contract
  drift, repository-boundary validation, all-target/all-feature build checking,
  `cargo deny`, gitleaks, and Commitizen preview;
- core library tests: 558 passed, with every additional binary/integration suite passing;
- `cargo audit`: no known vulnerabilities;
- optimized `cargo build --release --locked`: passed;
- contract regeneration: reproducible and left the working tree unchanged;
- gitleaks history and current-tree scans: no leaks;
- Commitizen dry run: `0.1.0` to `1.0.0`, no files modified;
- release dry run: binary archive, SHA-256 checksums, CycloneDX SBOM, and third-party
  notices generated locally; nothing published;
- Docker image: built successfully, `--help` passed, and runtime identity was 1000:1000;
- GitHub Actions CI run `33045712279`: full check and image jobs passed;
- remote default branch: `main`; remote visibility: private; remote tags: none;
- destination working tree: clean and synchronized with remote `main`.
