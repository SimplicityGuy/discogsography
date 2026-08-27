# GrooveMap SOPS Secure Enclave checkpoint

- Migration bead: `discogsography-2kpm.6`
- Verification date: 2026-08-27 UTC
- Infra pull request: [`groovemap-music/infra#2`](https://github.com/groovemap-music/infra/pull/2)
- Infra revision: `80e6f73` (`feat(secrets): prepare Secure Enclave SOPS ceremony`)
- Pull-request validation: [run 33032303617](https://github.com/groovemap-music/infra/actions/runs/33032303617), passed
- Status: blocked before identity generation on two operator decisions

## Verified behavior

The current upstream age-plugin-se documentation and the installed command help were
inspected. The Mac runs macOS 26.6.2 on arm64 and has the pinned age-plugin-se 0.2.1,
SOPS 3.13.3, and age 1.3.1 tools. No identity-generating command was run, and no identity
payload, recovery key, public recipient, ciphertext, or plaintext example was created.

age-plugin-se requires a compatible Mac with a Secure Enclave to generate an identity
and decrypt. Its identity is machine-bound and cannot be copied to a replacement Mac.
Version 0.2.1 defaults to `any-biometry-or-passcode`; biometric-only use is explicitly
selected with `any-biometry`. Upstream warns that `current-biometry` has different
enrollment-change behavior, so it will not be substituted implicitly.

SOPS commit
[`6157d86`](https://github.com/getsops/sops/commit/6157d86d75242cea4edaa4e32f492bc4e2ba46f0)
added generic age-plugin support and is an ancestor of v3.10.0. The installed SOPS 3.13.3
therefore supports `age1se...` plugin recipients when age-plugin-se is on `PATH`.

Authoritative sources:

- <https://github.com/remko/age-plugin-se>
- <https://github.com/getsops/sops>
- <https://github.com/getsops/sops/releases/tag/v3.10.0>

## Prepared non-secret scaffold

Infra PR #2 restricts creation to top-level `secrets/*.sops.yaml`,
`secrets/*.sops.json`, and `secrets/*.sops.env` files. It adds guarded recipes for
creating and round-trip-checking a random dummy ciphertext, decrypting every ciphertext
only to `/dev/null`, and running `sops updatekeys --yes` on every encrypted file.

The readiness gate requires SOPS 3.10 or newer, a reviewed age key group with at least
two distinct public recipients including one `age1se...` recipient, and an external
identity file with mode `0600`. It does not inspect or print identity contents. Example
generation currently exits with code 2 before creating a temporary file, because no
reviewed key group exists. Local formatting, OpenTofu validation, deterministic branding,
shell syntax, shellcheck, gitleaks, trufflehog, and the expected negative readiness tests
passed.

## Required operator decisions

1. Select Secure Enclave access control:
   - `any-biometry-or-passcode` (upstream default; Touch ID with passcode fallback), or
   - `any-biometry` (Touch-ID-only on this Mac; no passcode fallback).
2. Select an independent recovery mechanism. The recommended default is a separately
   passphrase-protected ordinary age identity stored offline and outside this Mac's
   failure domain. A hardware-backed recovery recipient is an alternative but requires a
   separately approved plugin and custody process.

No recipient will be invented or committed. After the operator chooses both policies,
the identity and recovery ceremony must occur outside every repository, only public
recipients may be added to `.sops.yaml`, and the generated dummy ciphertext must pass a
decrypt round trip and leak scan before PR #2 can be completed.
