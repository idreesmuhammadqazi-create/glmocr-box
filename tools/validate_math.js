const fs = require("fs");
const katex = require("katex");

const md = fs.readFileSync(process.argv[2], "utf8");
const segments = [];
const display = /\$\$([\s\S]+?)\$\$/g;
const inline = /(?<!\$)\$((?:[^$\n\\]|\\.)+?)(?<!\\)\$(?!\$)/g;

let m;
const protectedRanges = [];
while ((m = display.exec(md)) !== null) {
  segments.push({ kind: "display", tex: m[1], pos: m.index });
  protectedRanges.push([m.index, m.index + m[0].length]);
}
const inProtected = (i) => protectedRanges.some(([a, b]) => i >= a && i < b);
while ((m = inline.exec(md)) !== null) {
  if (!inProtected(m.index)) segments.push({ kind: "inline", tex: m[1], pos: m.index });
}

let failed = 0;
for (const s of segments) {
  try {
    katex.renderToString(s.tex, { throwOnError: true, displayMode: s.kind === "display" });
  } catch (e) {
    failed++;
    console.log(`FAIL [${s.kind}] @${s.pos}: ${e.message.slice(0, 120)}`);
    console.log(`  tex: ${s.tex.slice(0, 160)}`);
  }
}
console.log(`\n${segments.length} math segments, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
