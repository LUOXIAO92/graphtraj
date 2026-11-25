import { chromium } from 'playwright';
try { const b = await chromium.launch({ headless: true, executablePath: process.env.CHROME, args: ['--allow-file-access-from-files'] }); const p = await b.newPage(); await p.setContent('<button>ok</button>'); console.log('CHROMIUM-OK', await p.getByRole('button').innerText()); await b.close(); }
catch (e) { console.log('CHROMIUM-FAILED', String(e).slice(0, 1500)); }
