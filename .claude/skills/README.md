# Project Custom Skills

Project-specific skills for common tasks. These supplement the built-in skills.

## Creating a Custom Skill

Use the `anthropic-skills:skill-creator` skill:

```
/skill-creator
```

This guides you through building a new skill with:
- **Name** — how you'll invoke it (`/skill-name`)
- **Description** — what it does and when to use it
- **Prompt** — the instructions it follows
- **Tool access** — which tools the skill needs (read files, run tests, etc.)

## Example Custom Skills for This Project

### `/verify-map` — End-to-end map feature verification
- **When:** Before merging map rendering changes
- **Prompt:** "Drive the map UI, test zoom, pan, pin placement, marker info, responsiveness"
- **Tools:** Run dev server, browser navigation, screenshots

### `/api-test` — Integration test suite runner
- **When:** Testing FastAPI endpoints
- **Prompt:** "Run integration tests, report coverage gaps, suggest new tests"
- **Tools:** Bash, file read/write

### `/data-import-check` — Validate park data imports
- **When:** Adding new park data or updating imports
- **Prompt:** "Check data schema compliance, validate coordinates, detect duplicates"
- **Tools:** Bash, file read

---

## How to Use Custom Skills

Once created, invoke them like built-in skills:
```
/verify-map
/api-test
/data-import-check
```

I'll recognize them and use them in relevant contexts.
