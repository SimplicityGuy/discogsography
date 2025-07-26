#!/bin/bash
# Pre-commit hook to check for iOS wheels in uv.lock

if grep -q "ios_[0-9]\+_[0-9]\+_.*\.whl" uv.lock 2>/dev/null; then
    echo "❌ iOS wheels found in uv.lock!"
    echo "Run: ./scripts/remove-ios-wheels.sh"
    exit 1
fi
exit 0
