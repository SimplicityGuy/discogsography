# Vinyl Archaeology Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `before_year` time-travel filtering to the graph explore UI so users can scrub through decades and watch the music graph assemble itself.

**Architecture:** Thread an optional `before_year` parameter through all expand/count query functions and the `/api/expand` endpoint. Add two new endpoints (`/api/explore/year-range`, `/api/explore/genre-emergence`). Build a timeline scrubber UI component with play/pause animation and genre emergence highlights.

**Tech Stack:** Python 3.13 / FastAPI / Neo4j Cypher / JavaScript (D3.js, vanilla DOM) / Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-14-vinyl-archaeology-design.md`
