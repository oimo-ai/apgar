import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const ROOT = new URL("..", import.meta.url);
const SEMANTIC = [
  "bg",
  "surface",
  "surface-raised",
  "border",
  "border-strong",
  "text",
  "text-muted",
  "accent",
  "accent-text",
  "pass",
  "pass-bg",
  "fail",
  "fail-bg",
  "inconclusive",
  "inconclusive-bg",
  "sidebar",
  "sidebar-text",
  "sidebar-muted",
  "sidebar-active",
  "sidebar-strong",
];

const design = readFileSync(new URL("DESIGN.md", ROOT), "utf8");
let failed = false;
for (const name of SEMANTIC) {
  if (!design.includes(`light-${name}:`) || !design.includes(`dark-${name}:`)) {
    console.error(`DESIGN.md is missing semantic token ${name}`);
    failed = true;
  }
}

const color =
  /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(|\boklab\(|fonts\.googleapis\.com/g;

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      files.push(...walk(full));
      continue;
    }
    if (!/\.(ts|tsx|css)$/.test(entry) || entry.endsWith(".generated.css")) {
      continue;
    }
    files.push(full);
  }
  return files;
}

const src = new URL("src/", ROOT);
for (const file of walk(src.pathname)) {
  const text = readFileSync(file, "utf8");
  const lines = text.split("\n");
  lines.forEach((line, index) => {
    color.lastIndex = 0;
    if (color.test(line)) {
      console.error(`${file}:${index + 1}: ${line.trim()}`);
      failed = true;
    }
  });
}

if (failed) {
  process.exit(1);
}
