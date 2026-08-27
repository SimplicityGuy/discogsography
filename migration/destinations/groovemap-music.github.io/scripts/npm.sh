#!/usr/bin/env bash
set -euo pipefail

npm_tool_root="$(mise where npm:npm@12.0.2)"
npm_cli="${npm_tool_root}/node_modules/.mise/npm@12.0.2/node_modules/npm/bin/npm-cli.js"
node_tool_root="$(mise where node@24.20.0)"

export PATH="${node_tool_root}/bin:${PATH}"

exec node "${npm_cli}" "$@"
