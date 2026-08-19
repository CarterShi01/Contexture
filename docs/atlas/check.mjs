// Parse every mermaid block in the atlas and fail if any of them is invalid.
//
//   npm install jsdom@22
//   node docs/atlas/check.mjs
//
// The atlas is hand-maintained, and a mermaid syntax error does not announce
// itself until someone opens the page: the diagram is replaced by a bomb icon
// while the rest of the page renders normally. This script catches that before
// it ships, using the same vendored mermaid build the page itself loads.
//
// jsdom is required only by this check. Contexture itself has no dependencies.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { runInThisContext } from "node:vm";
import { JSDOM } from "jsdom";

const HERE = dirname(fileURLToPath(import.meta.url));
const ATLAS = process.argv[2] ?? join(HERE, "index.html");
const VENDOR = process.argv[3] ?? join(HERE, "vendor", "mermaid.min.js");

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  pretendToBeVisual: true,
  url: "http://localhost/",
});

// mermaid bundles its own DOMPurify, which needs a real window when it loads.
for (const key of [
  "navigator",
  "location",
  "Element",
  "SVGElement",
  "HTMLElement",
  "Node",
  "NodeFilter",
  "DocumentFragment",
  "DOMParser",
  "XMLSerializer",
  "getComputedStyle",
  "requestAnimationFrame",
  "MutationObserver",
  "trustedTypes",
]) {
  if (dom.window[key] !== undefined) {
    globalThis[key] = dom.window[key];
  }
}
globalThis.window = dom.window;
globalThis.document = dom.window.document;

// The bundle declares a top-level `var` and expects script scope, so it has to
// run through vm; new Function would scope that var locally and the bundle's
// final globalThis assignment would fail.
runInThisContext(readFileSync(VENDOR, "utf8"));
const mermaid = globalThis.mermaid;
if (!mermaid) {
  throw new Error(`${VENDOR} did not attach mermaid to globalThis`);
}

const html = readFileSync(ATLAS, "utf8");
const blocks = [...html.matchAll(/<pre class="mermaid">([\s\S]*?)<\/pre>/g)].map(
  (match) => match[1],
);

console.log(`checking ${blocks.length} mermaid blocks in ${ATLAS}\n`);

let failures = 0;
for (const [index, raw] of blocks.entries()) {
  const text = raw
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .trim();
  const kind = text.split("\n")[0].trim();
  try {
    await mermaid.parse(text);
    console.log(`  ok    block ${index}  ${kind}`);
  } catch (error) {
    failures += 1;
    const message = String(error?.message ?? error);
    console.log(`  FAIL  block ${index}  ${kind}`);
    console.log(
      message
        .split("\n")
        .slice(0, 10)
        .map((line) => "        " + line)
        .join("\n") + "\n",
    );
  }
}

if (failures) {
  console.log(`\n${failures} block(s) would render as a syntax error.`);
  process.exit(1);
}
console.log("\nall blocks parse.");
