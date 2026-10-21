(function () {
  function matchingIndexes(before, after, maxCells) {
    const leftLength = before.length;
    const rightLength = after.length;
    const matches = [];
    if (leftLength * rightLength > maxCells) {
      let prefix = 0;
      while (prefix < Math.min(leftLength, rightLength)
        && before[prefix] === after[prefix]) {
        matches.push([prefix, prefix]);
        prefix += 1;
      }
      const suffix = [];
      let left = leftLength - 1;
      let right = rightLength - 1;
      while (left >= prefix && right >= prefix && before[left] === after[right]) {
        suffix.push([left, right]);
        left -= 1;
        right -= 1;
      }
      return matches.concat(suffix.reverse());
    }

    const lengths = Array.from(
      { length: leftLength + 1 }, () => new Uint32Array(rightLength + 1),
    );
    for (let left = leftLength - 1; left >= 0; left -= 1) {
      for (let right = rightLength - 1; right >= 0; right -= 1) {
        lengths[left][right] = before[left] === after[right]
          ? lengths[left + 1][right + 1] + 1
          : Math.max(lengths[left + 1][right], lengths[left][right + 1]);
      }
    }
    let left = 0;
    let right = 0;
    while (left < leftLength && right < rightLength) {
      if (before[left] === after[right]) {
        matches.push([left, right]);
        left += 1;
        right += 1;
      } else if (lengths[left + 1][right] >= lengths[left][right + 1]) {
        left += 1;
      } else {
        right += 1;
      }
    }
    return matches;
  }

  function changedRanges(before, after) {
    const left = Array.from(before);
    const right = Array.from(after);
    const leftRanges = [];
    const rightRanges = [];
    if (Math.max(left.length, right.length) > 2000) {
      return [left.length ? [[0, left.length]] : [], right.length ? [[0, right.length]] : []];
    }
    let leftCursor = 0;
    let rightCursor = 0;
    for (const [leftIndex, rightIndex] of [
      ...matchingIndexes(left, right, 250000), [left.length, right.length],
    ]) {
      if (leftCursor < leftIndex) leftRanges.push([leftCursor, leftIndex]);
      if (rightCursor < rightIndex) rightRanges.push([rightCursor, rightIndex]);
      leftCursor = leftIndex + 1;
      rightCursor = rightIndex + 1;
    }
    return [leftRanges, rightRanges];
  }

  function buildMinutesDiff(before, after) {
    const leftLines = before.split("\n");
    const rightLines = after.split("\n");
    const rows = [];
    const cell = (lines, index, kind, highlights = []) => ({
      line_number: index + 1,
      text: lines[index],
      kind,
      highlights,
    });
    let leftCursor = 0;
    let rightCursor = 0;
    for (const [leftIndex, rightIndex] of [
      ...matchingIndexes(leftLines, rightLines, 1000000),
      [leftLines.length, rightLines.length],
    ]) {
      const count = Math.max(leftIndex - leftCursor, rightIndex - rightCursor);
      for (let offset = 0; offset < count; offset += 1) {
        const oldIndex = leftCursor + offset;
        const newIndex = rightCursor + offset;
        const hasOld = oldIndex < leftIndex;
        const hasNew = newIndex < rightIndex;
        const [oldRanges, newRanges] = changedRanges(
          hasOld ? leftLines[oldIndex] : "",
          hasNew ? rightLines[newIndex] : "",
        );
        rows.push({
          left: hasOld
            ? cell(leftLines, oldIndex, hasNew ? "changed" : "removed", oldRanges)
            : null,
          right: hasNew
            ? cell(rightLines, newIndex, hasOld ? "changed" : "added", newRanges)
            : null,
        });
      }
      if (leftIndex < leftLines.length && rightIndex < rightLines.length) {
        rows.push({
          left: cell(leftLines, leftIndex, "context"),
          right: cell(rightLines, rightIndex, "context"),
        });
      }
      leftCursor = leftIndex + 1;
      rightCursor = rightIndex + 1;
    }
    return {
      rows,
      change_count: rows.filter((row) => row.left?.kind !== "context").length,
    };
  }

  if (typeof window !== "undefined") window.MeetMindDiff = { buildMinutesDiff };
  if (typeof module !== "undefined") module.exports = { buildMinutesDiff };
}());
