# Tailwind CSS v4 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Tailwind CSS from v3 to v4 across dashboard and explore services, adopting CSS-first configuration patterns.

**Architecture:** Both services build Tailwind at Docker image time via a `css-builder` stage. The upgrade replaces JS config files with CSS-native `@theme`, `@plugin`, and `@source` directives, and switches the CLI from `tailwindcss` to `@tailwindcss/cli`. No runtime changes needed.

**Tech Stack:** Tailwind CSS v4, `@tailwindcss/cli`, `@tailwindcss/forms` (v4-compatible)

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `dashboard/tailwind.input.css` | Replace v3 directives with v4 `@import`, `@plugin`, `@source` |
| Delete | `dashboard/tailwind.config.js` | Config moves into CSS |
| Modify | `dashboard/Dockerfile:8-28` | Update CSS builder stage for v4 CLI |
| Modify | `explore/tailwind.input.css` | Replace v3 directives, add `@theme` for custom colors, `@plugin`, `@source` |
| Delete | `explore/tailwind.config.js` | Config moves into CSS |
| Modify | `explore/Dockerfile:8-27` | Update CSS builder stage for v4 CLI |
| Modify | `docs/dockerfile-standards.md:16-43,293-298` | Update Tailwind documentation to reflect v4 |
| Modify | `.gitignore:201` | Already has `dashboard/static/tailwind.css` — verify `explore/static/tailwind.css` is also covered |

---

### Task 1: Dashboard — Migrate CSS Input File

**Files:**
- Modify: `dashboard/tailwind.input.css`

- [ ] **Step 1: Replace dashboard/tailwind.input.css with v4 CSS-first config**

The current file has only three `@tailwind` directives and uses `@tailwindcss/forms` via `tailwind.config.js`. Move everything into CSS.

```css
@import "tailwindcss";
@plugin "@tailwindcss/forms";
@source "./static/index.html";
@source "./static/dashboard.js";
@source "./static/admin.html";
@source "./static/admin.js";
```

- [ ] **Step 2: Delete dashboard/tailwind.config.js**

```bash
git rm dashboard/tailwind.config.js
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/tailwind.input.css
git commit -m "refactor(dashboard): migrate Tailwind config to CSS-first v4 format

Replace tailwind.config.js with @import/@plugin/@source directives in
tailwind.input.css. The JS config is no longer needed."
```

---

### Task 2: Dashboard — Update Dockerfile CSS Builder Stage

**Files:**
- Modify: `dashboard/Dockerfile:8-28`

- [ ] **Step 1: Update the CSS builder stage**

Replace the current CSS builder stage (lines 8-28) with:

```dockerfile
# ── CSS build stage ────────────────────────────────────────────────────────────
# Replaces the Tailwind Play CDN (cdn.tailwindcss.com) with a locally-built
# stylesheet so we can serve it with a proper SRI hash.  Node is only needed
# at build time; the final image contains only the generated tailwind.css.
FROM node:24-slim AS css-builder

WORKDIR /build

# Copy only the files the CLI needs to generate the CSS
COPY dashboard/tailwind.input.css ./
COPY dashboard/static/index.html ./static/index.html
COPY dashboard/static/dashboard.js ./static/dashboard.js

# Install Tailwind v4 CLI + the forms plugin, then emit a minified stylesheet
RUN npm install @tailwindcss/cli@^4 @tailwindcss/forms --save-dev && \
    ./node_modules/.bin/tailwindcss \
        --input tailwind.input.css \
        --output tailwind.css \
        --minify
```

Key changes from v3:
- Remove `COPY dashboard/tailwind.config.js ./` — no longer exists
- Package: `tailwindcss@^3` → `@tailwindcss/cli@^4`
- Package: `@tailwindcss/forms@^0.5` → `@tailwindcss/forms` (v4-compatible version)
- Remove `--config tailwind.config.js` flag — config is now in the CSS file

- [ ] **Step 2: Build the Docker image to verify**

```bash
docker build -f dashboard/Dockerfile -t discogsography-dashboard:tailwind-v4-test .
```

Expected: Build succeeds, `tailwind.css` is generated in the final image.

- [ ] **Step 3: Commit**

```bash
git add dashboard/Dockerfile
git commit -m "build(dashboard): update Dockerfile CSS builder for Tailwind v4

Switch from tailwindcss@^3 to @tailwindcss/cli@^4. Remove --config flag
since configuration is now in the CSS input file."
```

---

### Task 3: Explore — Migrate CSS Input File

**Files:**
- Modify: `explore/tailwind.input.css`

- [ ] **Step 1: Replace explore/tailwind.input.css with v4 CSS-first config**

The explore service has custom colors mapped to CSS variables and component classes. The `@theme` block replaces `theme.extend.colors` from the JS config. The `@layer components` block stays as-is — v4 still supports `@layer`.

```css
@import "tailwindcss";
@plugin "@tailwindcss/forms";
@source "./static/index.html";
@source "./static/js/**/*.js";

@theme {
    --color-bg-void: var(--bg-void);
    --color-bg-deep: var(--bg-deep);
    --color-card-bg: var(--card-bg);
    --color-inner-bg: var(--inner-bg);
    --color-bg-hover: var(--bg-hover);
    --color-text-high: var(--text-high);
    --color-text-mid: var(--text-mid);
    --color-text-dim: var(--text-dim);
    --color-text-muted: var(--text-muted);
    --color-cyan-500: var(--cyan-500);
    --color-cyan-glow: var(--cyan-glow);
    --color-purple-500: var(--purple-500);
    --color-purple-300: var(--purple-300);
    --color-blue-accent: var(--blue-accent);
    --color-purple-accent: var(--purple-accent);
    --color-accent-green: var(--accent-green);
    --color-accent-yellow: var(--accent-yellow);
    --color-accent-red: var(--accent-red);
    --color-border-color: var(--border-color);
}

@layer components {
    /* Button base */
    .btn-base {
        @apply inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-bg-deep;
    }

    /* Button variants */
    .btn-primary {
        @apply btn-base bg-cyan-500 text-white hover:bg-cyan-glow focus:ring-cyan-500;
    }

    .btn-success {
        @apply btn-base bg-accent-green text-white hover:bg-green-700 focus:ring-accent-green;
    }

    .btn-warning {
        @apply btn-base bg-accent-yellow text-black hover:bg-yellow-500 focus:ring-accent-yellow;
    }

    .btn-secondary {
        @apply btn-base bg-purple-500 text-white hover:bg-purple-300 focus:ring-purple-500;
    }

    .btn-danger {
        @apply btn-base bg-accent-red text-white hover:bg-red-700 focus:ring-accent-red;
    }

    .btn-outline-secondary {
        @apply btn-base border border-border-color text-text-mid hover:bg-card-bg hover:text-text-high focus:ring-border-color;
    }

    .btn-outline-primary {
        @apply btn-base border border-cyan-500 text-cyan-500 hover:bg-cyan-500 hover:text-white focus:ring-cyan-500;
    }

    .btn-outline-danger {
        @apply btn-base border border-accent-red text-accent-red hover:bg-accent-red hover:text-white focus:ring-accent-red;
    }

    .btn-outline-warning {
        @apply btn-base border border-accent-yellow text-accent-yellow hover:bg-accent-yellow hover:text-black focus:ring-accent-yellow;
    }

    .btn-sm {
        @apply px-2 py-1 text-xs;
    }

    /* Form input */
    .form-input-dark {
        @apply w-full rounded border border-border-color bg-bg-deep text-text-high placeholder-text-mid px-3 py-2 text-sm focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 focus:outline-none;
    }

    /* Badge */
    .badge {
        @apply inline-flex items-center rounded px-2 py-0.5 text-xs font-medium;
    }

    /* Spinner */
    .spinner {
        @apply inline-block h-8 w-8 animate-spin rounded-full border-4 border-cyan-500 border-r-transparent;
    }
}
```

Note: In Tailwind v4, custom theme colors use the `--color-*` namespace. A `--color-cyan-500` entry generates utilities like `bg-cyan-500`, `text-cyan-500`, etc. Since the existing HTML already uses class names like `bg-cyan-500` and `text-text-high`, the generated utility names will match — no HTML changes needed.

- [ ] **Step 2: Delete explore/tailwind.config.js**

```bash
git rm explore/tailwind.config.js
```

- [ ] **Step 3: Commit**

```bash
git add explore/tailwind.input.css
git commit -m "refactor(explore): migrate Tailwind config to CSS-first v4 format

Replace tailwind.config.js with @import/@plugin/@source/@theme directives
in tailwind.input.css. Custom colors move from theme.extend.colors to
@theme { --color-*: ... } block. Component layer classes unchanged."
```

---

### Task 4: Explore — Update Dockerfile CSS Builder Stage

**Files:**
- Modify: `explore/Dockerfile:8-27`

- [ ] **Step 1: Update the CSS builder stage**

Replace the current CSS builder stage (lines 8-27) with:

```dockerfile
# ── CSS build stage ────────────────────────────────────────────────────────────
# Builds Tailwind CSS at build time so the final image serves a minified
# stylesheet.  Node is only needed at build time.
FROM node:24-slim AS css-builder

WORKDIR /build

# Copy only the files the CLI needs to generate the CSS
COPY explore/tailwind.input.css ./
COPY explore/static/index.html ./static/index.html
COPY explore/static/js/ ./static/js/

# Install Tailwind v4 CLI + the forms plugin, then emit a minified stylesheet
RUN npm install @tailwindcss/cli@^4 @tailwindcss/forms --save-dev && \
    ./node_modules/.bin/tailwindcss \
        --input tailwind.input.css \
        --output tailwind.css \
        --minify
```

Key changes from v3:
- Remove `COPY explore/tailwind.config.js ./` — no longer exists
- Package: `tailwindcss@^3` → `@tailwindcss/cli@^4`
- Package: `@tailwindcss/forms@^0.5` → `@tailwindcss/forms` (v4-compatible version)
- Remove `--config tailwind.config.js` flag — config is now in the CSS file

- [ ] **Step 2: Build the Docker image to verify**

```bash
docker build -f explore/Dockerfile -t discogsography-explore:tailwind-v4-test .
```

Expected: Build succeeds, `tailwind.css` is generated in the final image.

- [ ] **Step 3: Commit**

```bash
git add explore/Dockerfile
git commit -m "build(explore): update Dockerfile CSS builder for Tailwind v4

Switch from tailwindcss@^3 to @tailwindcss/cli@^4. Remove --config flag
since configuration is now in the CSS input file."
```

---

### Task 5: Update Documentation

**Files:**
- Modify: `docs/dockerfile-standards.md:16-43,293-298`

- [ ] **Step 1: Update the Tailwind CSS build stage documentation**

Replace lines 16-43 (the CSS build stage example and explanation) with:

```markdown
The dashboard uses a dedicated Node stage to run the Tailwind v4 CLI and produce a minified stylesheet
at image build time, eliminating any CDN dependency at runtime:

\`\`\`dockerfile
# ── CSS build stage ────────────────────────────────────────────────────────────
FROM node:24-slim AS css-builder

WORKDIR /build

# Copy only the files the CLI needs
COPY dashboard/tailwind.input.css ./
COPY dashboard/static/index.html ./static/index.html

# Install Tailwind v4 CLI + forms plugin, emit minified stylesheet
RUN npm install @tailwindcss/cli@^4 @tailwindcss/forms --save-dev && \
    ./node_modules/.bin/tailwindcss \
        --input tailwind.input.css \
        --output tailwind.css \
        --minify
\`\`\`

The generated `tailwind.css` is copied into the final stage:

\`\`\`dockerfile
COPY --from=css-builder --chown=discogsography:discogsography /build/tailwind.css /app/dashboard/static/tailwind.css
\`\`\`
```

- [ ] **Step 2: Update the Dashboard section note**

Replace the line at ~296:

```
- `css-builder` stage runs Tailwind CLI to produce `dashboard/static/tailwind.css`
```

with:

```
- `css-builder` stage runs Tailwind v4 CLI to produce `dashboard/static/tailwind.css`
```

- [ ] **Step 3: Verify .gitignore covers both generated CSS files**

Check that `.gitignore` contains entries for both:
- `dashboard/static/tailwind.css` (already present at line 201)
- `explore/static/tailwind.css` (verify — add if missing)

- [ ] **Step 4: Commit**

```bash
git add docs/dockerfile-standards.md .gitignore
git commit -m "docs: update Tailwind documentation for v4 upgrade"
```

---

### Task 6: Verify Docker Builds

- [ ] **Step 1: Build both services**

```bash
docker build -f dashboard/Dockerfile -t discogsography-dashboard:tailwind-v4-test . && \
docker build -f explore/Dockerfile -t discogsography-explore:tailwind-v4-test .
```

Expected: Both builds succeed.

- [ ] **Step 2: Verify the generated CSS files exist and contain expected content**

```bash
# Dashboard: check that generated CSS has form reset styles from @tailwindcss/forms
docker run --rm discogsography-dashboard:tailwind-v4-test cat /app/dashboard/static/tailwind.css | head -5

# Explore: check that generated CSS has custom color variables and component classes
docker run --rm discogsography-explore:tailwind-v4-test grep -c "btn-primary\|btn-base\|form-input-dark" /app/explore/static/tailwind.css
```

Expected: Dashboard CSS file exists and is non-empty. Explore CSS contains the component class definitions.

- [ ] **Step 3: Clean up test images**

```bash
docker rmi discogsography-dashboard:tailwind-v4-test discogsography-explore:tailwind-v4-test
```
