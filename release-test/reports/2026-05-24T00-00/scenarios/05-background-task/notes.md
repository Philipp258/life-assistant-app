# 05 — Background task

**Status:** red
**Severity:** blocker
**Reason:** blocked by 02. Background tasks are driven by the same
model used for chat. Brave Search key was successfully configured
(via the API workaround in 02), so the web-search tool would have
been available — but the agent never reaches the tool-calling stage
because the first model call fails.
