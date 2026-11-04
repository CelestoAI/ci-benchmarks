// A task slow enough that a cache hit is easy to see.
const fs = require("fs");
fs.mkdirSync("dist", { recursive: true });
setTimeout(() => {
  fs.writeFileSync("dist/out.txt", fs.readFileSync("src/index.txt", "utf8") + fs.readFileSync("src/salt.txt", "utf8"));
}, 5000);
