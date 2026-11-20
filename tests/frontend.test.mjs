import assert from "node:assert/strict";
import { test } from "node:test";
import { evidenceLabel, staticSchedule } from "../signal_atlas/static/edition.mjs";

const status = {
  timezone: "America/New_York", refresh_hours: [8, 16], stale_grace_minutes: 90,
  now: "2026-11-19T01:52:00Z", next_scheduled: "2026-11-19T13:00:00Z",
  previous_slot: "2026-11-18T21:00:00Z",
};

test("static status uses the reader's clock and waits for the grace period", () => {
  assert.deepEqual(staticSchedule(status, Date.parse("2026-11-19T14:29:59Z")), {
    due: "2026-11-18T21:00:00.000Z", next: "2026-11-19T21:00:00.000Z",
  });
  assert.deepEqual(staticSchedule(status, Date.parse("2026-11-19T14:30:00Z")), {
    due: "2026-11-19T13:00:00.000Z", next: "2026-11-19T21:00:00.000Z",
  });
});

test("refresh slots stay at the same local hour across Eastern daylight-saving transitions", () => {
  assert.deepEqual(staticSchedule(status, Date.parse("2026-03-08T12:00:00Z")), {
    due: "2026-03-07T21:00:00.000Z", next: "2026-03-08T20:00:00.000Z",
  });
  assert.deepEqual(staticSchedule(status, Date.parse("2026-11-01T12:59:00Z")), {
    due: "2026-10-31T20:00:00.000Z", next: "2026-11-01T13:00:00.000Z",
  });
  assert.deepEqual(staticSchedule(status, Date.parse("2026-11-01T14:30:00Z")), {
    due: "2026-11-01T13:00:00.000Z", next: "2026-11-01T21:00:00.000Z",
  });
});

test("claims from the same canonical document count as one source", () => {
  const doc = "https://example.com/filing";
  const evidence = [
    { canonical_url: doc, url: doc + "?utm_source=wire", stance: "supports" },
    { canonical_url: doc, url: doc + "#results", stance: "context" },
    { url: doc, stance: "challenges" },
  ];
  assert.equal(evidenceLabel({ evidence }), "3 claims · 1 source");
  assert.equal(evidenceLabel({ evidence: [...evidence, { url: "https://example.com/research" }] }), "4 claims · 2 sources");
});
