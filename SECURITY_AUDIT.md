# UAT Cleanup and Security Audit

Audit scope: `app/` and `tests/`, completed 2026-10-01. The review covered route authentication, SQL construction, filesystem boundaries, uploads, sessions, secrets, audit logging, worker behavior, exception handling, and dead/debug code.

## Critical

- Fixed merge-output path traversal. `output_filename` is now restricted to a simple PDF basename, preventing `..\\`, `/`, absolute paths, and oversized names from escaping document storage.
- Fixed global Hugging Face token overwrite. User job uploads and recording finalization no longer accept or persist an HF token; token configuration remains admin-only.
- Removed application-level file-size limits from document and audio uploads; partial files are still removed on upload failure.
- Fixed recording integrity risks. Writes are serialized, malformed metadata is rejected, finalized sessions reject new chunks, and finalization requires contiguous chunk indexes. Recording file-size limits were intentionally removed for the current product requirement.
- Fixed worker restart/concurrency gaps. Waiting jobs are atomically claimed, interrupted `processing` jobs are recovered to `waiting` at startup, and `wake()` now signals the worker.
- Fixed browser XSS risk in document actions by replacing inline handlers containing user-controlled tag text with event listeners and dataset values.

## Bugs Fixed

- Added missing persisted job metadata columns and migrations for duration, detected language, device, and compute type; these fields were being updated by the worker but were absent from the schema.
- Corrupt job `formats` JSON no longer crashes job reads; it is logged and treated as an empty list.
- Dynamic SQL update methods now allowlist column identifiers before interpolation.
- Document upload/version metadata failures now remove the already-written file or version directory instead of leaving orphaned data.
- PDF tool and SMTP failures no longer return raw exception messages, paths, or stack details to clients.
- Best-effort search-index failures now emit warnings instead of being silently swallowed.
- Added audit entries for successful login, logout, folder creation, tag changes, profile changes, transcript edits, recording chunks/finalization/cancellation, and log cleanup. Watermark text is no longer recorded verbatim.
- Added `soundfile==0.14.0` to `requirements.txt`; it is imported by the diarization compatibility layer but was previously undeclared.
- Added regression tests for traversal, oversized-upload cleanup, incomplete recordings, SQL identifier allowlisting, worker recovery, token isolation, and audit redaction.

## Dead Code Removed

- Removed unused `hashlib` and `hmac` imports from `app/main.py`.
- Removed the redundant local `shutil` import in the job-delete route.
- Replaced the no-op worker `wake()` implementation with a real event signal.
- Removed user-upload token persistence code that was both unsafe and unused by the frontend.
- No `print()`, `console.log()`, `TODO`, `FIXME`, or debugger artifacts were found in `app/` after cleanup. Remaining fallback `except` blocks in diarization and SMTP shutdown are intentional compatibility/cleanup paths and are logged or followed by a higher-level error.

## Auth Coverage

Public routes: `/`, `/admin/login`, `/api/login`, and `/api/admin/login`.

Authenticated user routes: `/home`, `/transcription`, `/documents`, `/api/me`, `/api/logout`, `/api/jobs`, `/api/search`, all `/api/documents*` routes, `/api/diarization/status`, `/api/recordings*`, `/api/jobs/{job_id}/preview`, `/api/jobs/{job_id}/outputs/{filename}`, and `/api/jobs/{job_id}` deletion. Job and recording ownership is checked separately after authentication.

Admin-only routes: `/admin`, all `/admin/settings*` and `/admin/*` settings pages, `/api/admin/documents/deleted`, `/api/admin/documents/{document_id}/restore`, all `/api/admin/users*`, both audit-log routes, log settings/cleanup, overview, HF settings, and notification settings/test routes.

The page routes use redirect checks; API routes use `current_user` or `current_admin` dependencies. No protected API route was found without the appropriate dependency.

## SQL, Files, Sessions, and Secrets

- Request values in database predicates and values are parameterized. Dynamic SQL is limited to internally allowlisted identifiers or generated placeholder lists.
- Document upload names are reduced to basenames and extension allowlisted. Download paths are resolved and containment-checked. Job output paths are containment-checked. Recording session IDs are character-allowlisted and containment-checked.
- Session tokens use `secrets.token_urlsafe(32)`. Cookies are `HttpOnly` and `SameSite=Strict`; session state is process-local and has no expiration or secure-cookie setting.
- Passwords are PBKDF2-HMAC-SHA256 hashes with per-password salts and constant-time comparison. SMTP passwords remain write-only in API responses but are stored plaintext in SQLite. HF tokens remain plaintext in the admin-managed environment file by design.
- No password, token, or API key is returned or logged by application code after these changes. Failed-login audit actor values still use the submitted username, which is an identifier rather than a secret.

## Findings Not Yet Fixed

- Login rate limiting is still absent. Repeated failed attempts are audited but not throttled. Deliberately deferred because the correct policy needs product decisions about per-account versus per-source limits, proxy identity, lockout behavior, and recovery UX.
- CSRF/origin protection is not implemented. `SameSite=Strict` materially reduces cross-site cookie submission, but a deliberate CSRF token or origin policy is still recommended before internet exposure.
- Sessions are in-memory, do not expire, are not shared across workers, and do not set `Secure`. Deliberately retained for this review because replacing them requires a deployment/session-store decision; use HTTPS and a shared expiring store before multi-process or public deployment.
- Documents are a shared authenticated repository: regular users can operate on any non-deleted document. This matches the current shared-folder behavior but differs from owner-isolated jobs and should be confirmed as a product decision before UAT.
- SMTP credentials are stored in plaintext `app_settings`. Encrypting them requires key-management and migration decisions; restrict database/file permissions in the interim.
- Worker shutdown still logs an error if a long-running transcription exceeds its 10-second join window. The heartbeat thread is fully joined, but interruptible model cancellation needs a deeper worker lifecycle design.
- Some generated-document database writes can still leave orphaned output directories if a later multi-document tool operation fails midway. Cleanup is now handled for direct uploads and versions; transactional cleanup for all derived-document batches is deferred to avoid changing tool semantics during this review.
- Dependency versions in `requirements.txt`: FastAPI 0.115.6, Uvicorn 0.34.0, faster-whisper 1.1.1, python-multipart 0.0.20, passlib 1.7.4, python-docx 1.1.2, pydantic-settings 2.7.1, pytest 8.3.4, httpx 0.28.1, pyannote.audio 3.3.2, soundfile 0.14.0, pypdf 6.19.0, reportlab 5.0.1. No live advisory database was available in this review, so these versions should still be checked with `pip-audit` before production deployment.

## Validation

Focused security/regression tests passed during the pass. The final full suite must be run from the project environment before UAT; expected baseline warnings are the existing Starlette/httpx and anyio deprecations.
