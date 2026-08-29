# Migration record

- Target: `groovemap-music/.github`
- Initial visibility: private
- Intended visibility: public only after a separate exposure review and approval
- Source subtree: `migration/repositories/org-profile/`
- Versioning: unversioned community/profile content
- License: preserved source license pending a separate licensing decision

This repository has no pre-existing product-code path to filter. Its useful history begins
with the reviewed preparation commit in the preserved monorepo migration branch. The
future extractor must clone the source repository and run an equivalent of:

```sh
git filter-repo \
  --path migration/repositories/org-profile/ \
  --path-rename migration/repositories/org-profile/:
```

Run that command only in a disposable clone, record the source and destination commit
counts, and verify the resulting tree before pushing. Never run it in the original
monorepo. No source tag is specific to this profile repository, so no historical tag is
promoted.
