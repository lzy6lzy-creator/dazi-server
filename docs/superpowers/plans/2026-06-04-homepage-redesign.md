# Homepage Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current technical homepage with a clean user-facing introduction page.

**Architecture:** Keep the site as a single static HTML file served by FastAPI. Store the selected GPT image asset in `app/static/assets/` and reference it from the hero. Add static regression tests to protect message hierarchy and prevent the technical sections from returning.

**Tech Stack:** Static HTML/CSS, FastAPI static files, Python `unittest` static checks.

---

### Task 1: Static Tests

**Files:**
- Create: `tests/test_homepage_static.py`

- [ ] **Step 1: Write tests**

Check that the homepage has the new ordinary-user hero, references the non-human hero image, explains AI matching in user language, keeps low-profile utility links, and no longer contains the old technology-focused sections.

- [ ] **Step 2: Run tests and verify red**

Run: `python3 -m unittest tests/test_homepage_static.py`

Expected: fails on the old homepage.

### Task 2: Homepage Rewrite

**Files:**
- Modify: `app/static/index.html`
- Create: `app/static/assets/hero-activity-cards.png`

- [ ] **Step 1: Copy selected hero asset**

Copy the selected generated non-human "warm object illustration" image into `app/static/assets/hero-activity-cards.png`.

- [ ] **Step 2: Replace the homepage**

Build sections:
- Hero with selected image, "想做的事，终于有人一起。", CTA buttons, and simple benefit chips.
- Three-step flow.
- "为什么靠谱" section explaining time, location, preference, and "双方 AI 先聊一轮".
- Activity category strip.
- Final CTA.
- Footer with low-profile `/docs` and `/admin` links.

### Task 3: Verification and Deployment

**Files:**
- Verify: `tests/test_homepage_static.py`

- [ ] **Step 1: Run static tests**

Run: `python3 -m unittest tests/test_homepage_static.py`

Expected: all tests pass.

- [ ] **Step 2: Check HTML and asset references**

Run curl or a local static server to confirm `/static/assets/hero-activity-cards.png` is reachable from the page.

- [ ] **Step 3: Deploy**

Copy `index.html` and `hero-activity-cards.png` into `dazi-api`, then verify `http://47.103.127.95:8000/` returns the new page.
