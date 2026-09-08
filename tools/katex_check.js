#!/usr/bin/env node
/* Batch KaTeX validator.
 * Reads a JSON array of {id, latex} from stdin, renders each with KaTeX in
 * strict mode, and writes a JSON array of {id, ok, error} to stdout.
 */
const katex = require("katex");

let input = "";
process.stdin.on("data", (d) => (input += d));
process.stdin.on("end", () => {
  let items;
  try {
    items = JSON.parse(input);
  } catch (e) {
    process.stdout.write(JSON.stringify([{ id: null, ok: false, error: "bad input json" }]));
    return;
  }
  const results = items.map((it) => {
    try {
      katex.renderToString(it.latex, {
        throwOnError: true,
        strict: true,
        displayMode: !!it.display,
      });
      return { id: it.id, ok: true, error: null };
    } catch (e) {
      return { id: it.id, ok: false, error: String(e.message || e) };
    }
  });
  process.stdout.write(JSON.stringify(results));
});
