const path = require("path");

function loadKatex() {
  try {
    return require("katex");
  } catch (e) {
    const dir = process.env.KATEX_NODE_MODULES || path.join(process.cwd(), "node_modules");
    return require(path.join(dir, "katex"));
  }
}

const katex = loadKatex();

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (input += d));
process.stdin.on("end", () => {
  let items = [];
  try {
    items = JSON.parse(input);
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: "bad input: " + e.message }));
    return;
  }
  const results = items.map((item) => {
    try {
      katex.renderToString(item.tex, {
        throwOnError: true,
        displayMode: !!item.display,
        strict: false,
      });
      return null;
    } catch (e) {
      return String((e && e.message) || e).slice(0, 300);
    }
  });
  process.stdout.write(JSON.stringify(results));
});
