// Shared build script: copies src/ into dist/ after a 5 s sleep,
// so a turbo cache hit is easy to see in step timing.
const fs = require("fs");
const path = require("path");

const cwd = process.cwd();
const name = require(path.join(cwd, "package.json")).name;
console.log(`[${name}] building (sleep 5 s)...`);

setTimeout(() => {
  const dist = path.join(cwd, "dist");
  fs.rmSync(dist, { recursive: true, force: true });
  fs.mkdirSync(dist, { recursive: true });
  for (const f of fs.readdirSync(path.join(cwd, "src"))) {
    fs.copyFileSync(path.join(cwd, "src", f), path.join(dist, f));
  }
  console.log(`[${name}] built at ${new Date().toISOString()}`);
}, 5000);
