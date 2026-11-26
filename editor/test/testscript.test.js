// Guard: the package "test" script must run every test/*.test.js (ED-05 CI residual).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

test("npm test script covers every test/*.test.js by glob", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url)));
  assert.equal(pkg.scripts.test, 'node --test "test/*.test.js"');
  const files = readdirSync(new URL(".", import.meta.url)).filter((f) => f.endsWith(".test.js"));
  assert.ok(files.length >= 23, `expected >=23 test files, found ${files.length}`);
});
