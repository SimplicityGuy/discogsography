set shell := ["bash", "-euo", "pipefail", "-c"]
npm := "scripts/npm.sh"

default:
    @just --list

# Install exactly the dependencies in package-lock.json.
setup:
    {{npm}} ci

# Fast, deterministic, credential-free pre-merge gate.
check: format-check lint typecheck test build validate-site license-check

format-check:
    {{npm}} run format:check

lint:
    {{npm}} run lint

typecheck:
    {{npm}} run typecheck

test:
    {{npm}} test

build:
    {{npm}} run build

validate-site:
    {{npm}} run validate:site

license-check:
    {{npm}} run licenses:check

# Network access is intentional and separate from check.
audit:
    {{npm}} audit --audit-level=high

dev:
    {{npm}} run dev

preview:
    {{npm}} run preview
