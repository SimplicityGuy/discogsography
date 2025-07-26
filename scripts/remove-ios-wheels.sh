#!/bin/bash
# Remove iOS-specific wheels from uv.lock to fix Docker builds
# iOS wheels are not compatible with Linux containers and cause parsing errors

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UV_LOCK="$PROJECT_ROOT/uv.lock"

if [ ! -f "$UV_LOCK" ]; then
    echo "❌ uv.lock not found at $UV_LOCK"
    exit 1
fi

echo "🔍 Checking for iOS-specific wheels in uv.lock..."

# Count iOS wheels before removal
IOS_COUNT=$(grep -c "ios_[0-9]\+_[0-9]\+_.*\.whl" "$UV_LOCK" || true)

if [ "$IOS_COUNT" -eq 0 ]; then
    echo "✅ No iOS-specific wheels found"
    exit 0
fi

echo "⚠️  Found $IOS_COUNT iOS-specific wheel(s)"
echo "🔧 Removing iOS-specific wheels..."

# Create backup
cp "$UV_LOCK" "$UV_LOCK.bak"

# Remove lines containing iOS wheels
# This removes the entire line containing iOS wheel references
sed -i '' '/ios_[0-9]\+_[0-9]\+_.*\.whl/d' "$UV_LOCK"

# Clean up any trailing commas from the last entry
# This handles cases where we removed the last item in a list
perl -i -0pe 's/,(\s*)\]/\1]/g' "$UV_LOCK"

echo "✅ iOS-specific wheels removed"
echo "💾 Backup saved to $UV_LOCK.bak"
echo ""
echo "ℹ️  This issue occurs when:"
echo "   - Dependencies with iOS support are added (e.g., Pillow)"
echo "   - uv.lock is regenerated on macOS with iOS platform support"
echo ""
echo "🚀 Next steps:"
echo "   1. Commit the updated uv.lock file"
echo "   2. Test Docker builds with: docker build -f <service>/Dockerfile ."
