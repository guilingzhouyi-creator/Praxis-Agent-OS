---
fonds: AGENT
series: issues
item_no: 000
type: specification
date: 2026-07-22
timestamp: 2026-07-22T19:50
author: OpenCode
keywords: [template, specification, convention]
relations: []
debt: []
---

# Praxis Issue Specification and Examples

## Specification

### File Naming
`{item_no:03d}_{type}_{title}.md`
Example: `001_event_ssr_implementation.md`

### Header Fields

| Field | Required | Description | Enum Values |
|:-----|:----:|:-----|:--------|
| `fonds` | 🔴 | Memory category | `PHASE` / `DESIGN` / `AGENT` / `REVIEW` |
| `series` | 🔴 | Issue category name | `skills` / `phase17` / `ux` etc. |
| `item_no` | 🔴 | 3-digit sequence number | `001`-`999` |
| `type` | 🔴 | Document type | `issue` / `decision` / `implementation` / `finding` / `specification` / `event` |
| `date` | 🔴 | Creation date | `YYYY-MM-DD` |
| `timestamp` | 🔴 | Precise time | `YYYY-MM-DDTHH:MM` |
| `author` | 🔴 | Creator | Agent name |
| `keywords` | 🟡 | Search tags | `[tag1, tag2]` |
| `relations` | 🟡 | Related memory IDs | `[PHASE-16-001]` |
| `debt` | 🟡 | Generated todos | `[gateway rsa upgrade]` |

### Body Specification
- Use `#` for title, `##` for section, `###` for subsection
- Conclusion first: first sentence summarizes the core of the issue
- At least one proposal, separate proposals with `### Proposal N`
- All proposals must have `Pros` `Cons` evaluation

---

## Example

```yaml
---
fonds: AGENT
series: skills
item_no: 001
type: issue
date: 2026-07-22
timestamp: 2026-07-22T19:50
author: OpenCode
keywords: [SSR, rendering, performance]
relations: [PHASE-16-003]
debt: [Migrate legacy template engine]
---
```

# Issue: Server-Side Rendering Support

All pages currently render on the client side, resulting in slow initial load and poor SEO. An SSR solution is needed.

## Proposal 1: Full Migration to Next.js

Migrate all existing Flask templates to Next.js.

- Pros: Mature ecosystem, active community, dual SSR/SSG support
- Cons: Full rewrite, 2-3 month timeline, incompatible with existing Flask routes

## Proposal 2: Flask + React Hybrid

Keep the Flask backend and integrate React SSR for key frontend pages.

- Pros: Incremental migration, can be rolled out in batches
- Cons: Increased architectural complexity, need to maintain two rendering pipelines
