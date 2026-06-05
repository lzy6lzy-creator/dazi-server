# Layered Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-layer memory system where event-specific preferences are stored separately from long-term user memories, and users can view, edit, and delete long-term memories on iOS and Android.

**Architecture:** The backend owns memory extraction, updating, storage, and API contracts. iOS and Android consume the expanded memory API from Profile screens and provide edit/delete controls. The first implementation uses deterministic event-memory generation plus rule-based long-term updates, keeping an LLM prompt hook for future refinement.

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL JSON columns, SwiftUI, Kotlin Compose, unittest, xcodebuild, Gradle.

---

### Task 1: Backend Memory Schema And API

**Files:**
- Modify: `app/models/user.py`
- Modify: `app/api/schemas.py`
- Modify: `app/api/users.py`
- Test: `tests/test_memory_api_helpers.py`

- [ ] **Step 1: Write failing tests**

Create tests for memory response expansion and update validation:

```python
from uuid import uuid4
import unittest

from app.api.schemas import MemoryUpdate
from app.models.user import AgentMemory


class MemoryApiHelperTests(unittest.TestCase):
    def test_memory_model_exposes_long_term_fields(self):
        memory = AgentMemory(
            user_id=uuid4(),
            type="style",
            content="喜欢直接总结后确认",
            key="style.confirmation",
            category="style",
            occurrence_count=2,
            status="active",
        )

        self.assertEqual(memory.key, "style.confirmation")
        self.assertEqual(memory.category, "style")
        self.assertEqual(memory.occurrence_count, 2)
        self.assertEqual(memory.status, "active")

    def test_memory_update_requires_content_or_active_change(self):
        with self.assertRaises(ValueError):
            MemoryUpdate().validate_change()

        valid = MemoryUpdate(content="不吃辣")
        self.assertEqual(valid.validate_change(), valid)
```

- [ ] **Step 2: Verify tests fail**

Run: `.venv311/bin/python -m unittest tests.test_memory_api_helpers -q`

Expected: fail because `MemoryUpdate` and new model fields are missing.

- [ ] **Step 3: Implement schema and API**

Add long-term fields to `AgentMemory`, expand `MemoryResponse`, add `MemoryUpdate`, add `PATCH /agents/me/memories/{memory_id}` and `DELETE /agents/me/memories/{memory_id}`. DELETE should soft-disable memory by setting `is_active=false` and `status=inactive`.

- [ ] **Step 4: Verify tests pass**

Run: `.venv311/bin/python -m unittest tests.test_memory_api_helpers -q`

- [ ] **Step 5: Commit backend API slice**

Commit server changes with message `Add editable memory API`.

### Task 2: Backend Event Memory And Long-Term Updater

**Files:**
- Modify: `app/models/user.py`
- Create: `app/services/memory_service.py`
- Modify: `app/api/agent_chat.py`
- Modify: `app/services/prompt_builder.py`
- Test: `tests/test_memory_service.py`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: Write failing tests**

Cover:

- Event draft preferences create event memory candidates.
- “今晚想吃火锅” is event-only.
- “我不能吃辣” creates or reinforces long-term constraint.
- Repeated event candidate weakly upgrades after two occurrences.
- `style` memories are supported in prompt formatting.

- [ ] **Step 2: Verify tests fail**

Run: `.venv311/bin/python -m unittest tests.test_memory_service tests.test_prompt_builder -q`

- [ ] **Step 3: Implement memory service**

Create a focused service with:

- `build_event_memory_candidates(draft, event_id, user_id)`
- `derive_long_term_memory_actions(text, event_memories, existing_memories)`
- `apply_long_term_memory_actions(db, user_id, actions, event_id)`
- `extract_and_update_memories_after_publish(user_id, event_id, user_message, draft)`

The first version should use deterministic rules and JSON-safe structures, not rely on LLM availability.

- [ ] **Step 4: Wire publish flow**

Replace `_extract_memories_background` internals with the new service while preserving the background task call site.

- [ ] **Step 5: Verify tests pass**

Run: `.venv311/bin/python -m unittest tests.test_memory_service tests.test_prompt_builder -q`

- [ ] **Step 6: Commit memory updater slice**

Commit server changes with message `Implement layered memory updater`.

### Task 3: iOS Memory Editing

**Files:**
- Modify: `dazi/Models/AgentMemory.swift`
- Modify: `dazi/Services/APIClient.swift`
- Modify: `dazi/Services/DataStore.swift`
- Modify: `dazi/Views/Profile/ProfileView.swift`

- [ ] **Step 1: Extend client model**

Add optional fields matching the expanded backend response and support `style`.

- [ ] **Step 2: Add API methods**

Add PATCH and DELETE calls for memories.

- [ ] **Step 3: Add DataStore actions**

Add `updateMemory(id:content:)` and `deleteMemory(id:)`, then refresh local memory list.

- [ ] **Step 4: Update Profile UI**

Make each memory card show type/category/confidence and expose edit/delete controls. Editing should be inline via sheet or alert.

- [ ] **Step 5: Build iOS**

Run: `xcodebuild -project dazi.xcodeproj -scheme dazi -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17' build`

- [ ] **Step 6: Commit iOS slice**

Commit iOS changes with message `Add editable memory controls`.

### Task 4: Android Memory Editing

**Files:**
- Modify: `app/src/main/java/com/dazi/app/data/model/AgentMemory.kt`
- Modify: `app/src/main/java/com/dazi/app/data/remote/dto/MemoryDto.kt`
- Modify: `app/src/main/java/com/dazi/app/data/remote/ApiService.kt`
- Modify: `app/src/main/java/com/dazi/app/data/repository/UserRepository.kt`
- Modify: `app/src/main/java/com/dazi/app/ui/profile/ProfileViewModel.kt`
- Modify: `app/src/main/java/com/dazi/app/ui/profile/ProfileScreen.kt`

- [ ] **Step 1: Extend client model**

Add expanded memory fields and `STYLE` type.

- [ ] **Step 2: Add API methods**

Add PATCH and DELETE calls for memories.

- [ ] **Step 3: Add ViewModel actions**

Add edit/delete methods that refresh memory list and expose a user-visible error string.

- [ ] **Step 4: Update Profile UI**

Add memory edit/delete controls with a compact dialog.

- [ ] **Step 5: Build Android**

Run: `./gradlew assembleDebug`. If Java Runtime is unavailable, report the environment blocker.

- [ ] **Step 6: Commit Android slice**

Commit Android changes with message `Add editable memory controls`.

### Task 5: Full Verification

**Files:**
- No production files expected unless verification exposes an issue.

- [ ] **Step 1: Run server tests**

Run: `.venv311/bin/python -m unittest discover -s tests -q`

- [ ] **Step 2: Run iOS build**

Run: `xcodebuild -project dazi.xcodeproj -scheme dazi -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17' build`

- [ ] **Step 3: Run Android build**

Run: `./gradlew assembleDebug`

- [ ] **Step 4: Ensure clean worktrees**

Run `git status --short` in all three repos.
