import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const dist = resolve(root, 'dist');
if (!dist.startsWith(root)) throw new Error('Unsafe dist path');

const html = await readFile(resolve(root, 'my-portfolio_5.html'), 'utf8');
if (!html.includes('runPortfolioABComparison') || !html.includes('portfolioHealthResult')) {
  throw new Error('Required final features are missing from the HTML');
}

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await writeFile(resolve(dist, 'index.html'), html, 'utf8');
await writeFile(resolve(dist, 'my-portfolio_5.html'), html, 'utf8');
await cp(resolve(root, 'data'), resolve(dist, 'data'), { recursive: true });
await cp(resolve(root, 'firebase-config.js'), resolve(dist, 'firebase-config.js'));
console.log('production build OK: dist/index.html + static data cache');
