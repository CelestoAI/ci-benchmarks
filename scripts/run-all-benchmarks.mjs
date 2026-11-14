import { spawn } from 'node:child_process';

const workflows = [
  'suite-rust.yml',
  'suite-node.yml',
  'suite-docker.yml',
  'suite-cache.yml',
  'suite-hardware.yml',
  'suite-burst.yml',
];
const ref = process.env.BENCHMARK_REF ?? 'main';

console.log(`Dispatching all six Celesto benchmark workflows concurrently on ${ref}.`);
console.log('Concurrent suites can compete for runner capacity and affect timings.');

const outcomes = await Promise.all(workflows.map((workflow) => new Promise((resolve) => {
  const child = spawn('gh', ['workflow', 'run', workflow, '--ref', ref], { stdio: 'inherit' });
  child.once('error', (error) => {
    console.error(`${workflow}: ${error.message}`);
    resolve({ workflow, code: 1 });
  });
  child.once('exit', (code) => resolve({ workflow, code: code ?? 1 }));
})));

const failed = outcomes.filter(({ code }) => code !== 0);
if (failed.length) {
  console.error(`Failed to dispatch: ${failed.map(({ workflow }) => workflow).join(', ')}`);
  process.exitCode = 1;
} else {
  console.log('All six workflows were dispatched. Follow them in GitHub Actions.');
}
