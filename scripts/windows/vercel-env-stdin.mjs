import { spawn } from 'node:child_process';

const [vercelEntry, ...args] = process.argv.slice(2);
if (!vercelEntry) throw new Error('Vercel entrypoint required');
const input = process.env.RADAR_EDITORIAL_TEMP_INPUT;
delete process.env.RADAR_EDITORIAL_TEMP_INPUT;

const child = spawn(process.execPath, [vercelEntry, ...args], {
  env: process.env,
  stdio: ['pipe', 'pipe', 'pipe'],
  windowsHide: true,
});
child.stdout.pipe(process.stdout);
child.stderr.pipe(process.stderr);
child.stdin.end(input === undefined ? undefined : Buffer.from(input, 'utf8'));
child.on('error', (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on('exit', (code) => {
  process.exitCode = code ?? 1;
});
