// Writes the TypeScript sources of the Turborepo fixture: PACKAGES packages,
// FILES files each. Deterministic, so the same commit gives the same Turbo hashes.
// Sources are written into src/ (not ignored), so Turbo hashes them.
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const PACKAGES = 8, FILES = 400, here = new URL('.', import.meta.url).pathname;
const name = (i) => `pkg-${String(i).padStart(2, '0')}`;
for (let p = 0; p < PACKAGES; p++) {
  const dir = join(here, 'packages', name(p));
  mkdirSync(join(dir, 'src'), { recursive: true });
  const deps = p === PACKAGES - 1 ? Object.fromEntries([...Array(p).keys()].map((i) => [name(i), '*'])) : {};
  writeFileSync(join(dir, 'package.json'), JSON.stringify({ name: name(p), version: '1.0.0', private: true,
    main: 'dist/index.js', types: 'dist/index.d.ts', scripts: { build: 'tsc -p .' }, dependencies: deps }, null, 2) + '\n');
  writeFileSync(join(dir, 'tsconfig.json'), JSON.stringify({ compilerOptions: { target: 'ES2022', module: 'commonjs',
    declaration: true, strict: true, outDir: 'dist', rootDir: 'src', skipLibCheck: true }, include: ['src'] }, null, 2) + '\n');
  const index = [];
  for (let f = 0; f < FILES; f++) {
    const lines = [`export interface Rec${f}<T> { id: number; value: T; tags: ReadonlyArray<string>; next?: Rec${f}<T> }`];
    for (let k = 0; k < 20; k++) {
      lines.push(`export function fn${f}_${k}<T extends { id: number }>(xs: ReadonlyArray<T>, m: Map<number, Rec${f}<T>>): Array<Rec${f}<T>> {
  return xs.filter((x) => x.id % ${k + 2} === 0).map((x) => m.get(x.id) ?? { id: x.id * ${k + 1}, value: x, tags: ['p${p}', 'f${f}', 'k${k}'] });
}`);
    }
    writeFileSync(join(dir, 'src', `m${f}.ts`), lines.join('\n') + '\n');
    index.push(`export * as m${f} from './m${f}';`);
  }
  writeFileSync(join(dir, 'src', 'index.ts'), index.join('\n') + '\n');
}
