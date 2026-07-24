import { spawnSync } from 'node:child_process';

const scriptArgs = process.argv.slice(2);
if (!scriptArgs.length) throw new Error('Python script path is required');
const candidates = [
  process.env.PYTHON ? [process.env.PYTHON] : null,
  ['python3'],
  ['python'],
  ['py', '-3'],
].filter(Boolean);

for (const [command, ...prefix] of candidates) {
  const result = spawnSync(command, [...prefix, ...scriptArgs], { stdio: 'inherit' });
  if (!result.error) process.exit(result.status ?? 1);
  if (result.error.code !== 'ENOENT') throw result.error;
}
throw new Error('Python 3 executable not found. Set the PYTHON environment variable.');
