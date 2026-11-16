const {spawn} = require('node:child_process');
const path = require('node:path');
const child = spawn('python3', [path.join(process.env.GITHUB_WORKSPACE, '.harness/scripts/cache-concurrency-paired.py'), 'run'], {stdio: 'inherit', env: {...process.env, MATRIX_NODE: process.execPath}});
child.on('error', () => {console.error('Driver failed to start.'); process.exitCode = 1;});
child.on('exit', code => {process.exitCode = code ?? 1;});
