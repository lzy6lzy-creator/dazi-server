# Admin Console Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the service admin and matching test admin into one easy-to-use operational console.

**Architecture:** Keep backend business APIs unchanged. Make `app/static/admin.html` the single console shell and let `/match-test` serve the same shell, with JavaScript opening the Test Lab tab when the path is `/match-test`. Add static regression tests that protect the current matching preview response contract and shared admin token behavior.

**Tech Stack:** FastAPI static routes, standalone HTML/CSS/JavaScript, Python `unittest` static checks.

---

### Task 1: Static Regression Tests

**Files:**
- Create: `tests/test_admin_console_static.py`

- [ ] **Step 1: Write failing tests**

```python
from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminConsoleStaticTests(unittest.TestCase):
    def admin_html(self) -> str:
        return (ROOT / "app/static/admin.html").read_text(encoding="utf-8")

    def test_match_test_route_reuses_unified_admin_console(self):
        source = (ROOT / "app/main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        route_return = None
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "match_test_page":
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Call) and getattr(stmt.func, "id", None) == "FileResponse":
                        route_return = stmt.args[0].value

        self.assertEqual(route_return, "app/static/admin.html")

    def test_admin_console_contains_test_lab_with_shared_auth(self):
        html = self.admin_html()

        self.assertIn('id="adminToken"', html)
        self.assertIn("localStorage", html)
        self.assertIn('data-panel="testlab"', html)
        self.assertIn("/api/admin/test/generate", html)
        self.assertIn("/api/admin/test/match-preview-all", html)
        self.assertIn("/api/admin/test/stats", html)
        self.assertIn("/api/admin/test/cleanup", html)

    def test_admin_preview_uses_current_matching_preview_contract(self):
        html = self.admin_html()

        self.assertIn("total_recalled", html)
        self.assertIn("total_passed", html)
        self.assertIn("city_normalized", html)
        self.assertIn("candidates", html)
        self.assertIn("similarity", html)
        self.assertIn("filter_reason", html)
        self.assertNotIn("data.thresholds", html)
        self.assertNotIn("data.pipeline", html)
        self.assertNotIn("coarse_rank_top10", html)

    def test_dangerous_admin_actions_require_confirmation(self):
        html = self.admin_html()

        for action in [
            "matchAll",
            "resetAllEvents",
            "generateTestData",
            "cleanupTestData",
        ]:
            marker = f"async function {action}"
            start = html.index(marker)
            end = html.find("async function ", start + len(marker))
            block = html[start:] if end == -1 else html[start:end]
            self.assertIn("confirmAction", block, action)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify red**

Run: `python3 -m unittest tests/test_admin_console_static.py`

Expected: fails because `/match-test` still serves `match_test.html`, the unified Test Lab tab is missing, matching preview still reads `data.thresholds`/`data.pipeline`, and destructive actions are not consistently confirmed.

### Task 2: Unified Static Console

**Files:**
- Modify: `app/static/admin.html`
- Modify: `app/main.py`
- Optional compatibility file: `app/static/match_test.html`

- [ ] **Step 1: Replace `admin.html` with a unified shell**

The shell must include these panels and ids so tests and operators can rely on stable landmarks:

```html
<button class="nav-item active" data-panel="overview">概览</button>
<button class="nav-item" data-panel="events">事件</button>
<button class="nav-item" data-panel="matching">匹配</button>
<button class="nav-item" data-panel="testlab">测试实验</button>
<button class="nav-item" data-panel="prompts">Prompts</button>
<button class="nav-item" data-panel="rooms">聊天室</button>
<button class="nav-item" data-panel="logs">日志</button>
```

The JavaScript must provide one `requestAdmin(path, options)` helper that always attaches `Authorization: Bearer ${token}` when a token exists and persists the token in `localStorage`.

- [ ] **Step 2: Implement current preview contract rendering**

`renderSinglePreview(data)` and `renderPreviewList(previews)` must read:

```javascript
data.event;
data.city_normalized;
data.threshold;
data.candidates;
data.total_recalled;
data.total_passed;
candidate.event;
candidate.similarity;
candidate.passed;
candidate.status;
candidate.filter_reason;
```

No frontend code may read `data.thresholds`, `data.pipeline`, or `coarse_rank_top10`.

- [ ] **Step 3: Implement Test Lab inside the same shell**

The Test Lab controls must call:

```javascript
requestAdmin('/api/admin/test/generate?user_count=200&events_per_user=5', { method: 'POST' });
requestAdmin('/api/admin/test/match-preview-all?limit=30');
requestAdmin('/api/admin/test/stats');
requestAdmin('/api/admin/test/cleanup', { method: 'DELETE' });
```

`/match-test` path must open this tab by default.

- [ ] **Step 4: Add confirmations for dangerous actions**

These functions must call `confirmAction(...)` before making requests:

```javascript
async function matchAll() {}
async function resetAllEvents() {}
async function generateTestData() {}
async function cleanupTestData() {}
```

- [ ] **Step 5: Route `/match-test` to unified console**

Change `match_test_page()` in `app/main.py` to:

```python
@app.get("/match-test")
async def match_test_page():
    """匹配系统测试可视化页面"""
    return FileResponse("app/static/admin.html")
```

### Task 3: Verification

**Files:**
- Verify: `tests/test_admin_console_static.py`

- [ ] **Step 1: Run targeted tests**

Run: `python3 -m unittest tests/test_admin_console_static.py`

Expected: all tests pass.

- [ ] **Step 2: Run existing low-risk backend tests**

Run: `python3 -m unittest tests/test_a2a_matcher.py tests/test_matching_policy.py tests/test_location_policy.py tests/test_event_location_vector_experiment.py tests/test_admin_console_static.py`

Expected: all selected tests pass.

- [ ] **Step 3: Start local server and smoke check static routes**

Run: `ADMIN_TOKEN=devtoken DATABASE_URL=postgresql+asyncpg://invalid JWT_SECRET=devsecret123 python3 -m uvicorn app.main:app --host 127.0.0.1 --port 18080`

Then request:

```bash
curl -s http://127.0.0.1:18080/admin | grep '统一后台'
curl -s http://127.0.0.1:18080/match-test | grep '测试实验'
```

Expected: both routes return the unified console markup.
