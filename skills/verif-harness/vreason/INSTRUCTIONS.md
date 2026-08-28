# VReason mode

Use VReason only when schemas and deterministic tools cannot resolve intent
conflicts, uncertain impact, triage hypotheses, or alternative closure
strategies.

Run `reason capabilities`, then prepare `reason request --role ROLE --backend
BACKEND`. Role and Backend are independent. A backend response must contain
diagnosis, confidence, proposed_actions, risk, human_review, and
evidence_requirements. Availability is a capability, not permission. Do not
silently fall back between Codex, Kimi, and Claude, and never turn model output
into Human approval or verification evidence.
