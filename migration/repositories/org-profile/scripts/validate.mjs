import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const REQUIRED_FILES = [
  ".github/CODEOWNERS",
  ".github/workflows/ci.yml",
  "LICENSE",
  "NOTICE.md",
  "README.md",
  "docs/community-health.md",
  "docs/publication-runbook.md",
  "policy/community-health.json",
  "policy/public-exposure.json",
  "profile/README.md",
  "profile/assets/avatar.svg",
  "profile/assets/banner-dark.svg",
  "profile/assets/banner-light.svg",
  "profile/assets/checksums.sha256",
];

const COMMUNITY_HEALTH_PATHS = [
  "CODE_OF_CONDUCT.md",
  "CONTRIBUTING.md",
  "FUNDING.yml",
  "GOVERNANCE.md",
  "SECURITY.md",
  "SUPPORT.md",
  "ISSUE_TEMPLATE",
  "PULL_REQUEST_TEMPLATE.md",
  ".github/ISSUE_TEMPLATE",
  ".github/PULL_REQUEST_TEMPLATE.md",
];

const EXPOSURE_PATTERNS = [
  [
    "private-age-identity",
    new RegExp(`${["AGE", "PLUGIN", "SE"].join("-")}-[A-Z0-9-]+|${["AGE", "SECRET", "KEY"].join("-")}-`),
  ],
  ["private-key", new RegExp(`${["-----BEGIN", "(?:[A-Z ]+ )?PRIVATE", "KEY-----"].join(" ")}`)],
  ["github-token", /\b(?:ghp|github_pat)_[A-Za-z0-9_]{12,}\b/],
  ["host-local-path", /(?:\/Users\/|\/var\/folders\/|[A-Z]:\\Users\\)/],
  ["secret-assignment", /\b(?:password|secret|token|api[_-]?key)\s*[:=]\s*["'][^"']{8,}["']/i],
];

function walk(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if ([".git", ".build", "node_modules"].includes(entry.name)) continue;
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) files.push(...walk(path));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}

export function extractLinks(markdown) {
  const links = [];
  for (const match of markdown.matchAll(/!?\[[^\]]*\]\(([^)\s]+)(?:\s+["'][^"']*["'])?\)/g)) {
    links.push(match[1]);
  }
  for (const match of markdown.matchAll(/\b(?:src|srcset|href)="([^"]+)"/g)) {
    links.push(match[1]);
  }
  return links;
}

export function findExposureIssues(content) {
  return EXPOSURE_PATTERNS.filter(([, pattern]) => pattern.test(content)).map(([name]) => name);
}

export function validateExternalLink(link, allowedHosts) {
  const url = new URL(link);
  if (url.protocol !== "https:") return `external link must use https: ${url.protocol}`;
  if (!allowedHosts.includes(url.hostname)) return `external host is not allowlisted: ${url.hostname}`;
  return null;
}

function readJson(path) {
  return JSON.parse(readFileSync(resolve(ROOT, path), "utf8"));
}

function checkRequiredFiles(errors) {
  for (const path of REQUIRED_FILES) {
    if (!existsSync(resolve(ROOT, path))) errors.push(`${path}: required file is missing`);
  }
}

function checkMarkdown(errors, allowedHosts) {
  for (const path of walk(ROOT).filter((file) => file.endsWith(".md"))) {
    const display = relative(ROOT, path);
    const content = readFileSync(path, "utf8");
    if (!content.endsWith("\n")) errors.push(`${display}: missing final newline`);
    if (content.split("\n").some((line) => /[ \t]+$/.test(line))) errors.push(`${display}: trailing whitespace`);

    for (const link of extractLinks(content)) {
      if (link.startsWith("#")) continue;
      if (/^[a-z][a-z0-9+.-]*:/i.test(link)) {
        try {
          const issue = validateExternalLink(link, allowedHosts);
          if (issue) errors.push(`${display}: ${issue}`);
        } catch {
          errors.push(`${display}: malformed external link`);
        }
        continue;
      }

      const localPath = decodeURIComponent(link.split("#", 1)[0]);
      if (!localPath) continue;
      const target = resolve(dirname(path), localPath);
      if (!target.startsWith(`${ROOT}/`) || !existsSync(target)) {
        errors.push(`${display}: broken or escaping local link: ${link}`);
      }
    }
  }
}

function checkProfile(errors) {
  const checksumPath = resolve(ROOT, "profile/assets/checksums.sha256");
  for (const line of readFileSync(checksumPath, "utf8").trim().split("\n")) {
    const match = line.match(/^([a-f0-9]{64})  ([A-Za-z0-9.-]+)$/);
    if (!match) {
      errors.push("profile/assets/checksums.sha256: malformed checksum line");
      continue;
    }
    const [, expected, filename] = match;
    const assetPath = resolve(ROOT, "profile/assets", filename);
    if (!existsSync(assetPath) || !statSync(assetPath).isFile()) {
      errors.push(`profile/assets/${filename}: promoted asset is missing`);
      continue;
    }
    const actual = createHash("sha256").update(readFileSync(assetPath)).digest("hex");
    if (actual !== expected) errors.push(`profile/assets/${filename}: checksum mismatch`);
  }

  const profile = readFileSync(resolve(ROOT, "profile/README.md"), "utf8");
  for (const repository of [
    "catalog-api",
    "musicbrainz-graph-enricher",
    "musicbrainz-sql-loader",
    "python-libraries",
    "operations-console",
    "discogs-graph-enricher",
    "analytics-engine",
    "database-schema",
    "discogs-sql-loader",
    "operations-toolkit",
    "catalog-ingestion",
    "graph-explorer",
    "mcp-server",
  ]) {
    if (!profile.includes(`https://github.com/groovemap-music/${repository}`)) {
      errors.push(`profile/README.md: approved repository is missing: ${repository}`);
    }
  }
  if (!profile.includes("https://groovemap.music")) errors.push("profile/README.md: canonical website is missing");
}

function checkLicense(errors) {
  const license = readFileSync(resolve(ROOT, "LICENSE"), "utf8");
  const notice = readFileSync(resolve(ROOT, "NOTICE.md"), "utf8");
  if (!license.includes("PolyForm Noncommercial License 1.0.0")) errors.push("LICENSE: preserved source license is missing");
  if (!license.includes("Required Notice: Copyright (c) 2023-2026 Robert Wlodarczyk")) errors.push("LICENSE: required notice is missing");
  if (!notice.includes("Space Grotesk font binaries were not promoted")) errors.push("NOTICE.md: excluded-font notice is missing");
}

function checkExposure(errors, policy, communityHealth) {
  const repository = policy.repository ?? {};
  if (repository.owner !== "groovemap-music" || repository.name !== ".github") {
    errors.push("policy/public-exposure.json: wrong repository identity");
  }
  if (repository.currentVisibility !== "private") errors.push("policy/public-exposure.json: initial visibility must remain private");
  if (repository.intendedVisibility !== "public" || repository.publicTransitionApprovalRequired !== true) {
    errors.push("policy/public-exposure.json: public transition must remain approval-gated");
  }
  if (repository.githubPagesEnabled !== false) errors.push("policy/public-exposure.json: Pages does not belong to the profile repository");
  if (policy.canonicalWebsite !== "https://groovemap.music") errors.push("policy/public-exposure.json: canonical website is incorrect");

  if (!Array.isArray(communityHealth.inheritedFiles) || communityHealth.inheritedFiles.length !== 0) {
    errors.push("policy/community-health.json: inherited files require a separate reviewed policy change");
  }
  for (const path of COMMUNITY_HEALTH_PATHS) {
    if (existsSync(resolve(ROOT, path))) errors.push(`${path}: undeclared inherited community-health file`);
  }

  for (const path of walk(ROOT)) {
    const display = relative(ROOT, path);
    const content = readFileSync(path, "utf8");
    for (const rule of findExposureIssues(content)) errors.push(`${display}: exposure rule matched: ${rule}`);
  }
}

export function validate(section = "all") {
  const errors = [];
  const exposure = readJson("policy/public-exposure.json");
  const communityHealth = readJson("policy/community-health.json");
  checkRequiredFiles(errors);
  if (["all", "markdown"].includes(section)) checkMarkdown(errors, exposure.allowedExternalHosts ?? []);
  if (["all", "profile"].includes(section)) checkProfile(errors);
  if (["all", "license"].includes(section)) checkLicense(errors);
  if (["all", "exposure"].includes(section)) checkExposure(errors, exposure, communityHealth);
  return errors;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const section = process.argv[2] ?? "all";
  const validSections = ["all", "markdown", "profile", "license", "exposure"];
  if (!validSections.includes(section)) {
    console.error(`unknown validation section: ${section}`);
    process.exit(2);
  }
  const errors = validate(section);
  if (errors.length > 0) {
    for (const error of errors) console.error(`ERROR ${error}`);
    process.exit(1);
  }
  console.log(`validated ${section}`);
}
