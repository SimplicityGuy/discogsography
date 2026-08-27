# Organization profile publication runbook

## Preconditions

Keep `groovemap-music/.github` private until all of these have been reviewed explicitly:

- every profile statement and repository name is approved for public disclosure;
- linked repositories either exist or their temporarily unavailable links are accepted;
- the current license and notices are suitable for public distribution;
- `just check` passes from a clean checkout;
- a secret scan of the prepared tree and retained history reports no verified secret; and
- an organization owner approves the public visibility transition.

Repository creation, initial push, and the private-to-public change are separate external
actions. OpenTofu must model the intended state, and its complete plan must receive the
migration's required apply approval before it changes visibility.

## Publish and verify

After the approved visibility change:

1. open `https://github.com/groovemap-music` while signed out;
2. confirm the light and dark banners render without clipping;
3. test every profile link and verify private repositories do not reveal content;
4. check the profile at narrow and wide viewport sizes;
5. confirm no shared community-health file is unexpectedly inherited; and
6. record the repository revision, Actions run, reviewer, and verification date in the
   migration evidence.

If any exposure is unexpected, change the repository back to private and investigate
before retrying. The rollback changes visibility only; do not delete the repository or
rewrite its prepared history.

## Manual organization avatar

The `.github` repository cannot set the GitHub organization avatar. After the profile and
asset review, an organization owner may upload
[`profile/assets/avatar.svg`](../profile/assets/avatar.svg) through the organization's
owner-only profile settings. Before doing so, confirm its checksum against the promotion
manifest and retain the previous avatar locally for rollback. Verify the result while
signed out. This step requires separate approval and is not performed by validation or
OpenTofu.
