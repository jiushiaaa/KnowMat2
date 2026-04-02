# Third Round Cleanup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce remaining medium-risk debt by trimming zero-call schema conversion helpers and validating whether the remaining dependency declarations can be safely reduced.

**Architecture:** Work in two tracks. First, use TDD to protect the live schema-conversion compatibility paths, then remove only helper code that has no runtime entry and no test dependency. Second, verify the remaining `langchain` and `pandas` declarations against actual imports and test execution before changing dependency manifests.

**Tech Stack:** Python 3.11+, pytest, setuptools/pyproject, KnowMat schema_converter pipeline

---

## Chunk 1: Rules And Dead Code

### Task 1: Protect active schema compatibility paths

**Files:**
- Modify: `d:\AI\KnowMat\tests\test_schema_converter.py`
- Modify: `d:\AI\KnowMat\src\knowmat\schema_converter.py`

- [ ] **Step 1: Write failing tests for still-supported conversion behavior**
- [ ] **Step 2: Run targeted pytest to verify the new test fails for the expected reason**
- [ ] **Step 3: Make the minimal implementation change needed to preserve supported behavior**
- [ ] **Step 4: Re-run the targeted pytest until it passes**

### Task 2: Remove zero-call variable-family helpers if they remain unreferenced

**Files:**
- Modify: `d:\AI\KnowMat\src\knowmat\schema_converter.py`
- Test: `d:\AI\KnowMat\tests\test_schema_converter.py`

- [ ] **Step 1: Re-check helper references immediately before editing**
- [ ] **Step 2: Remove only helpers that have no call path from `convert()` or tests**
- [ ] **Step 3: Run targeted pytest covering nearby schema conversion behavior**
- [ ] **Step 4: Stop and keep the code if any regression signal appears**

## Chunk 2: Dependency Reduction

### Task 3: Validate remaining manifest candidates

**Files:**
- Modify: `d:\AI\KnowMat\pyproject.toml`
- Modify: `d:\AI\KnowMat\requirements.txt`
- Modify: `d:\AI\KnowMat\environment.yml`

- [ ] **Step 1: Re-check live imports for `langchain` and `pandas`**
- [ ] **Step 2: Remove only declarations that are unsupported by code or required workflows**
- [ ] **Step 3: Keep notebook-only dependencies if the repository still treats notebooks as first-class**
- [ ] **Step 4: Run full pytest after each manifest batch**

## Chunk 3: Verification And Report

### Task 4: Verify and summarize

**Files:**
- Modify: `d:\AI\KnowMat\README.md` if any docs references drift
- Create or update: session cleanup report in final handoff

- [ ] **Step 1: Run `python -m pytest` from repository root**
- [ ] **Step 2: Review the git diff for deletions, manifest drift, and lingering references**
- [ ] **Step 3: Summarize removed items, retained risks, and evidence**
