# Security Vulnerabilities Roadmap - v6.1

**Date:** 2026-04-07  
**Review Scope:** Single-user, one-man project perspective  
**Total Open Alerts:** 16 Dependabot alerts

---

## Critical Priority (Must Fix)

### ⛔ #7: LangChain Serialization Injection (CRITICAL)
- **Package:** langchain-core
- **Risk:** Enables secret extraction in dumps/loads APIs
- **Single-User Impact:** HIGH - if any sensitive data (API keys, tokens) is serialized/loaded
- **Context:** This is a foundational vulnerability affecting core LangChain functionality
- **Action:** Create GitHub issue for immediate remediation; upgrade langchain-core as soon as patch available

---

## High Priority (Create Issues, Fix in Upcoming Release)

### #8, #4, #5: urllib3 Decompression Issues (3x HIGH)
- **Package:** urllib3
- **Issues:**
  - #8: Decompression-bomb safeguards bypassed when following HTTP redirects (streaming)
  - #4: Unbounded links in decompression chain
  - #5: Streaming API improperly handles highly compressed data
- **Single-User Impact:** MEDIUM-HIGH - affects httpx which you use directly; DoS via malicious compressed responses
- **Context:** All three are decompression-related; bundled fix in single urllib3 upgrade
- **Action:** Create GitHub issue; upgrade urllib3 to latest patched version

### #1: Starlette O(n²) DoS via Range Header (HIGH)
- **Package:** starlette
- **Risk:** DoS via malicious Range header merging in FileResponse
- **Single-User Impact:** MEDIUM - affects your FastAPI app if it serves files or uses Range requests
- **Action:** Create GitHub issue; upgrade starlette to patch version

### #16: LangChain Path Traversal (HIGH)
- **Package:** langchain-core
- **Risk:** Path traversal in legacy `load_prompt` functions
- **Single-User Impact:** MEDIUM - only if using `load_prompt()` with untrusted paths
- **Context:** Part of broader LangChain issues (#3, #10, #7); coordinated fix recommended
- **Action:** Create GitHub issue; coordinate with #7

### #3: LangChain Template Injection (HIGH)
- **Package:** langchain-core
- **Risk:** Template injection via attribute access in prompt templates
- **Single-User Impact:** MEDIUM-HIGH - if using prompt templates with user input
- **Context:** Part of broader LangChain issue set
- **Action:** Create GitHub issue; part of LangChain upgrade

### #6: LangGraph SQLite SQL Injection (HIGH)
- **Package:** langgraph-checkpoint-sqlite
- **Risk:** SQL injection via metadata filter key in list method
- **Single-User Impact:** MEDIUM - only if you use SQLite checkpointer with untrusted metadata keys
- **Context:** Specific to checkpoint feature; check if actively used
- **Action:** Create GitHub issue; assess actual usage

### #11: yt-dlp Command Injection (HIGH)
- **Package:** yt-dlp
- **Risk:** Arbitrary command injection via `--netrc-cmd` option
- **Single-User Impact:** LOW-MEDIUM - only exploitable if passing untrusted arguments to `--netrc-cmd`
- **Context:** You have direct yt-dlp dependency; need to verify if `--netrc-cmd` is used
- **Action:** Audit code; create issue if `--netrc-cmd` is used or could be used

---

## Medium Priority (Can Wait for v6.1, Roadmap for v6.2+)

### #14: orjson Recursion DoS (HIGH severity, medium urgency)
- **Package:** orjson
- **Risk:** No recursion limit for deeply nested JSON documents → DoS
- **Single-User Impact:** MEDIUM - only exploitable with deeply nested JSON parsing
- **Workaround:** Limit JSON depth in application logic
- **Action:** Plan for v6.2; upgrade orjson when convenient

### #12: LangGraph BaseCache Unsafe Deserialization (MEDIUM)
- **Package:** langgraph-checkpoint
- **Risk:** Deserialization of untrusted data may lead to RCE
- **Single-User Impact:** MEDIUM - only if deserializing untrusted checkpoint data
- **Context:** Part of LangGraph checkpoint infrastructure
- **Action:** Monitor for patches; upgrade as part of checkpoint security pass

### #13: LangGraph Checkpoint Unsafe Msgpack (MEDIUM)
- **Package:** langgraph
- **Risk:** Unsafe msgpack deserialization in checkpoint loading
- **Single-User Impact:** MEDIUM - only if loading untrusted checkpoints
- **Context:** Related to #12; same feature area
- **Action:** Monitor; coordinate with #12

### #9: LangSmith SSRF via Tracing Header (MEDIUM)
- **Package:** langsmith
- **Risk:** SSRF via tracing header injection
- **Single-User Impact:** LOW-MEDIUM - requires attacker to inject malicious tracing headers
- **Context:** Client SDK for LangSmith monitoring
- **Action:** Plan for v6.2; upgrade langsmith with next release cycle

### #15: Requests Insecure Temp File Reuse (MEDIUM)
- **Package:** requests
- **Risk:** Insecure temp file reuse in `extract_zipped_paths()` utility
- **Single-User Impact:** LOW - only if using requests' internal zip extraction (rare)
- **Workaround:** Use system tools for zip handling
- **Action:** Plan for v6.2; not urgent

---

## Low Priority (Monitor)

### #10: LangChain SSRF via image_url Token Counting (LOW)
- **Package:** langchain-core
- **Risk:** SSRF in ChatOpenAI.get_num_tokens_from_messages with image URLs
- **Single-User Impact:** LOW - very specific condition; only if using image token counting with untrusted URLs
- **Action:** Monitor; will be fixed in LangChain upgrade for #7

---

## Summary & Recommendations

### Immediate Actions (This Week)
1. **Create issue:** LangChain #7 (CRITICAL) - serialization injection
2. **Create issue:** urllib3 (#8, #4, #5) - decompression issues  
3. **Create issue:** Starlette #1 - Range header DoS
4. **Create issue:** LangChain #16 + #3 - path traversal & template injection
5. **Audit:** yt-dlp usage - verify `--netrc-cmd` is not used; if not, low priority
6. **Assess:** LangGraph SQLite #6 - check if checkpoint feature is active

### v6.1 Roadmap (This Sprint)
- Fix #7, #8/#4/#5, #1 (all upstream-dependent)
- Fix #16, #3 as part of broader LangChain upgrade
- Audit yt-dlp; fix #11 if applicable
- Assess and fix #6 if SQLite checkpoints are used

### v6.2 Roadmap (Next Sprint)
- #14, #12, #13 (LangGraph/orjson) - monitor patches
- #9, #15 (LangSmith, requests) - non-critical upgrades
- #10 - monitor via LangChain updates

### Single-User Project Considerations
- **No untrusted input:** Most of these vulnerabilities require untrusted input (malicious prompts, compromised API responses, etc.). For a single-user project, threat surface is lower.
- **Feature-specific:** Several issues only trigger if using specific features (SQLite checkpoints, `--netrc-cmd`, etc.); audit code for actual exposure.
- **Upstream-dependent:** Many are in third-party libraries; patches depend on upstream releases. Focus on what you can control (code audit, feature gates).
- **Prioritize for stability:** urllib3 and Starlette are foundational; fix those early.

---

## Tracking
- See GitHub Issues (created separately) for implementation tasks
- Use labels: `security`, `vulnerability`, `dependencies`
- Link back to Dependabot alerts in each issue
