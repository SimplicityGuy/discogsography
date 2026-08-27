import assert from "node:assert/strict";
import test from "node:test";

import { extractLinks, findExposureIssues, validateExternalLink } from "./validate.mjs";

test("extracts Markdown and HTML asset links", () => {
  const markdown = "[site](https://groovemap.music)\n<img src=\"./assets/banner.svg\">\n";
  assert.deepEqual(extractLinks(markdown), ["https://groovemap.music", "./assets/banner.svg"]);
});

test("accepts only https links on an allowlisted host", () => {
  const hosts = ["github.com", "groovemap.music"];
  assert.equal(validateExternalLink("https://groovemap.music/docs", hosts), null);
  assert.match(validateExternalLink("http://groovemap.music", hosts), /must use https/);
  assert.match(validateExternalLink("https://example.com", hosts), /not allowlisted/);
});

test("reports sensitive material by rule name without echoing it", () => {
  const privateKeyMarker = ["-----BEGIN", "PRIVATE", "KEY-----"].join(" ");
  assert.deepEqual(findExposureIssues(privateKeyMarker), ["private-key"]);
  assert.deepEqual(findExposureIssues("ordinary public profile text"), []);
});
