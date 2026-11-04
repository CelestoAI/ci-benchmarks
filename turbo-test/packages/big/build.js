// A 300 MiB random output: it cannot compress, so the artifact takes the block upload path (A-04).
const fs = require("fs");
const crypto = require("crypto");
fs.mkdirSync("dist", { recursive: true });
const fd = fs.openSync("dist/big.bin", "w");
for (let i = 0; i < 300; i++) fs.writeSync(fd, crypto.randomBytes(1024 * 1024));
fs.closeSync(fd);
