# Synthetic sample 3 — not real data

This file is a synthetic sample and **not real data**; it exists only to exercise the demo.

## Context

A *small* service returns a status for one request.

## Gap

The service has no defined answer when the request is malformed.

---

### Method

1. Send a malformed request.
2. Record the status code.
3. Compare it with the documented table.

```js
const status = 400; // invented placeholder
```

## Finding

The synthetic result is a **single** documented status, not a range.
