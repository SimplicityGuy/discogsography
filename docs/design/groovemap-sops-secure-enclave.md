# GrooveMap SOPS Secure Enclave evidence

- Migration bead: `discogsography-2kpm.6`
- Verification date: 2026-08-27 UTC
- Infra pull request: [`groovemap-music/infra#2`](https://github.com/groovemap-music/infra/pull/2)
- Infra ceremony revision: `2c2edb2f5ba579770aac87e01e1c311998006ca6`
- Infra action-runtime revision: `582e8f010d4af692d4d70fbdfd56e4cc7704f088`
- Merge commit: `a7ecb5ad390f22b8f3db6376c505871d65979d53`
- Pull-request validation: [run 33037481893](https://github.com/groovemap-music/infra/actions/runs/33037481893), passed
- Status: complete; primary and recovery paths independently verified

## Tooling and verified behavior

The installed command help and current upstream sources were inspected before generation.
The ceremony used age-plugin-se 0.2.1, SOPS 3.13.3, age 1.3.1, and 1Password CLI
2.39.0. The GitHub validation workflow was also updated to the pinned Node-24-based
actions/checkout v7.0.1 and jdx/mise-action v4.3.0 releases after GitHub reported the
previous Node 20 runtimes as deprecated.

age-plugin-se generated the project identity with the explicit
`any-biometry-or-passcode` access-control policy and `se` recipient type. The identity is
bound to this Mac's Secure Enclave, remains outside all repositories at
`~/.config/age/groovemap-music-infra.txt`, and has mode `0600`. Its private payload was
not printed, pasted, uploaded, or committed. Only its public `age1se...` recipient is in
`.sops.yaml`.

SOPS 3.13.3 supports the `age1se...` plugin recipient when age-plugin-se is on `PATH`.
The relevant generic plugin support entered SOPS before v3.10.0. Authoritative sources:

- <https://github.com/remko/age-plugin-se>
- <https://github.com/getsops/sops>
- <https://github.com/getsops/sops/releases/tag/v3.10.0>
- <https://developer.1password.com/docs/cli/>

## Independent recovery

The recovery identity is an ordinary age identity held as a Document named
`GrooveMap SOPS recovery identity` in the operator's existing 1Password `Private` vault.
The identity streamed directly from `age-keygen` into 1Password through desktop-app CLI
authorization. It was retrieved only through pipes for recipient and decryption checks;
no persistent recovery identity file was written. Only the public `age1...` recovery
recipient is committed.

This recovery identity is protected by 1Password. It is not Secure Enclave-backed and is
not misrepresented as having a separate age passphrase. Successful recovery depends on
the 1Password account recovery process remaining usable from a replacement Mac.

## Repository configuration and evidence

`.sops.yaml` restricts creation to top-level `secrets/*.sops.yaml`,
`secrets/*.sops.json`, and `secrets/*.sops.env` files. One key group contains the public
Secure Enclave and recovery recipients, so either identity can recover a SOPS data key.
Readiness checks require SOPS 3.10 or newer, both public recipients, an `age1se...`
recipient, and the external primary identity with mode `0600`.

The following checks passed without printing secret values or private identities:

- random dummy data encrypted directly to `secrets/example.sops.yaml` and semantically
  round-tripped without a tracked plaintext intermediate;
- `sops filestatus` reported the example as encrypted;
- the Secure Enclave identity decrypted every ciphertext to `/dev/null`;
- `SOPS_AGE_KEY_CMD` streamed the 1Password Document into SOPS and independently
  decrypted every ciphertext to `/dev/null`;
- `sops updatekeys --yes` confirmed every ciphertext already used the reviewed recipients;
- OpenTofu backend-disabled initialization and validation passed;
- deterministic branding validation passed;
- shellcheck, gitleaks, and TruffleHog passed with no leaks.

No OpenTofu import, plan, or apply was run as part of this bead. No repository, team,
ruleset, visibility, Pages, DNS, package, or release resource was changed.
