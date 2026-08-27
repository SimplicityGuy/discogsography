# Third-party notices

## @img/sharp-libvips-darwin-arm64 1.3.3

The locked macOS Apple-silicon development graph includes
`@img/sharp-libvips-darwin-arm64` as an optional, transitive platform package through
Astro 7.2.8 and Sharp 0.35.4. The package contains libvips and declares
`LGPL-3.0-or-later`.

- Source: <https://github.com/lovell/sharp-libvips>
- License terms: <https://www.gnu.org/licenses/lgpl-3.0.html>
- Upstream project: <https://sharp.pixelplumbing.com>

This package is a local build/image-tool dependency. GrooveMap's site uses direct static
SVG references and does not distribute libvips, Sharp, a dynamic library, or a native
Node module in the generated Pages artifact. `just license-check` verifies that boundary.
If a future build distributes the native library or uses it to create shipped derivative
assets, its LGPL notice, relinking/source-access, and any other applicable obligations
must be reassessed before publication.

## @img/sharp-libvips-linux-x64 1.3.3

The locked Ubuntu x64 CI graph includes the corresponding optional libvips platform
package through Astro 7.2.8 and Sharp 0.35.4. It also declares `LGPL-3.0-or-later`.

- Source: <https://github.com/lovell/sharp-libvips>
- License terms: <https://www.gnu.org/licenses/lgpl-3.0.html>
- Upstream project: <https://sharp.pixelplumbing.com>

It has the same build-only boundary: the generated Pages artifact contains no libvips,
Sharp, dynamic library, or native Node module. Distribution requires a fresh obligations
review.
