const test = require("node:test");
const assert = require("node:assert/strict");

const { buildMinutesDiff } = require("../app/static/minutes_diff.js");

test("aligns unchanged lines and highlights edited Chinese characters", () => {
  const diff = buildMinutesDiff(
    "# 结论\n- 使用第一版计划。\n- 删除项\n## 后续",
    "# 结论\n- 使用第二版计划。\n## 后续\n- 新增项",
  );

  assert.equal(diff.change_count, 3);
  assert.equal(diff.rows[0].left.kind, "context");
  assert.equal(diff.rows[1].left.kind, "changed");
  assert.equal(diff.rows[1].right.kind, "changed");
  const oldLine = diff.rows[1].left;
  const newLine = diff.rows[1].right;
  const highlighted = (cell) => cell.highlights.map(([start, end]) => (
    Array.from(cell.text).slice(start, end).join("")
  )).join("");
  assert.equal(highlighted(oldLine), "一");
  assert.equal(highlighted(newLine), "二");
  assert.equal(diff.rows[2].left.kind, "removed");
  assert.equal(diff.rows[2].right, null);
  assert.equal(diff.rows[4].left, null);
  assert.equal(diff.rows[4].right.kind, "added");
});

test("handles identical text and Unicode code points", () => {
  assert.equal(buildMinutesDiff("# 同一版\n", "# 同一版\n").change_count, 0);
  const diff = buildMinutesDiff("- 状态😀旧", "- 状态😀新");
  assert.deepEqual(diff.rows[0].left.highlights, [[5, 6]]);
  assert.deepEqual(diff.rows[0].right.highlights, [[5, 6]]);
});
