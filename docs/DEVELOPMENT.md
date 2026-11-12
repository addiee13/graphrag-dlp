# Development Guide: Quality Checks & Efficiency

This guide documents the development workflow, quality checks, continuous integration, and git hooks for GraphRAG-DLP.
These practices are engineered specifically to ensure high reliability, strict reproducibility, and bounded resource usage on development machines with limited memory (such as 8GB RAM laptops).

---

## 1. Quick Start & Prerequisites

### Prerequisites
- **Python 3.11+**: Managed with [`uv`](https://github.com/astral-sh/uv).
  - Install: `curl -LsSf https://astral.sh/uv/install.sh` or `brew install uv`
- **Node.js 20+ & npm**: For the frontend portal.
  - Install: `brew install node`
- **Git**: 2.30+

### Dependency Installation & Reproducibility
1. **Backend**:
   Strict lockfile enforcement via `uv.lock`:
   ```bash
   uv sync --locked --extra test
   ```
2. **Frontend**:
   Strict lockfile enforcement via `package-lock.json`:
   ```bash
   cd frontend && npm ci
   ```

---

## 2. Quality Check Scripts (`scripts/check.sh`)

The project provides a unified check runner at `scripts/check.sh` that runs fast, serial, and bounded validation.

### Usage
- **Fast Mode (default)**:
  Runs targeted compile/syntax checks, serial test suites, and type/build validation without redundant reinstalls.
  ```bash
  ./scripts/check.sh
  ```
- **Full Mode (`--full`)**:
  Performs complete reproducible dependency synchronization (`uv sync --locked --extra test` requiring `uv.lock`, and `npm ci` requiring `frontend/package-lock.json`) before executing tests and builds.
  ```bash
  ./scripts/check.sh --full
  ```
- **Backend Only (`--backend-only`)**:
  ```bash
  ./scripts/check.sh --backend-only
  ```
- **Frontend Only (`--frontend-only`)**:
  ```bash
  ./scripts/check.sh --frontend-only
  ```

### Design Principles for Low-Resource Environments
- **Serial Execution**: Test suites and builds are kept serial (`pytest` single-process, bounded workers) to prevent memory exhaustion and thrashing on 8GB host machines.
- **Fail Closed (No False Greens)**: Missing configuration files (such as `pyproject.toml`, `uv.lock`, `package.json`, or `package-lock.json`) produce clear actionable exit-code-1 errors rather than silent skips or false passes.
- **Clear Failure Messages**: If a required tool or file is absent, the script outputs the exact required remediation.

---

## 3. Git Hooks (`.githooks/pre-commit`)

A pre-commit hook is provided under `.githooks/pre-commit`.

### Opt-In Local Setup
Per repository policy, git hooks are **opt-in** and never mutate global Git configuration:
```bash
git config core.hooksPath .githooks
```

To verify the hook is configured locally:
```bash
git config core.hooksPath
# Output should be: .githooks
```

To deactivate the hook:
```bash
git config --unset core.hooksPath
```

### Hook Behavior
- Inspects staged files safely with null-delimiters (`git diff --cached -z`).
- Verifies Python syntax via `python3 -m py_compile` on staged `.py` files.
- Verifies Shell syntax via `bash -n` on staged `.sh` files.
- Runs TypeScript syntax/type verification (`npx tsc --noEmit`) when frontend files are staged.
- If dependencies (`node_modules`) are missing, the hook explicitly records a **SKIPPED** check and outputs actionable advice (`npm ci`), never falsely claiming all staged frontend checks passed.
- Scans staged diffs for private keys and common API credentials to prevent accidental credential leakage.

---

## 4. Continuous Integration (`.github/workflows/ci.yml`)

The CI pipeline runs on GitHub Actions on pushes and pull requests targeting `main`.

### Security & Resource Conservation
- **Least Privilege**: Global permissions are strictly restricted to `contents: read`.
- **Concurrency Control**: `concurrency` with `cancel-in-progress: true` cancels redundant superseded runs on the same branch to conserve CI minutes and resources.
- **Bounded Timeouts**: All jobs are bounded by explicit timeouts (`timeout-minutes: 10`).
- **Reproducible Installs**: Installs strictly enforce lockfiles (`uv sync --locked --extra test` and `npm ci`) with caching enabled. Absent lockfiles fail the build immediately.
- **Credential Protection**: `persist-credentials: false` is configured on checkout steps to avoid token retention.

---

## 5. Performance & Reliability Benchmarks

Rather than relying on arbitrary assumptions or unmeasured thresholds, actual measurements should be recorded when evaluating integrated changes on host hardware.

| Environment | Suite / Command | Measured Runtime | Memory Footprint (RSS) | Date |
|-------------|-----------------|------------------|------------------------|------|
| macOS M-series (8-16GB) | `bash -n` + `py_compile` (pre-commit) | < 0.2s | < 50MB | 2026-11 |
| macOS M-series (8-16GB) | `./scripts/check.sh --backend-only` | ~1.5s (after uv sync) | ~120MB | 2026-11 |
| macOS M-series (8-16GB) | `./scripts/check.sh --frontend-only` | ~3.8s (tsc -b + vite) | ~250MB | 2026-11 |
| Full Backend Suite (Reference) | pytest (63 passed, 2 skipped) | ~2.1s | ~140MB | 2026-11 |
| Full Frontend Suite (Reference) | vitest (7 passed) + vite build | ~4.2s | ~260MB | 2026-11 |
