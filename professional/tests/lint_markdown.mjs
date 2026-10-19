// Invoke the Markdownlint engine with literal paths; no glob/TOML CLI dependencies.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {lint} from 'markdownlint/promise';
const root = path.resolve(import.meta.dirname, '../..');
const require = createRequire(import.meta.url);
const config = require(path.join(root, '.markdownlint-cli2.cjs')).config;
const args = process.argv.slice(2).filter(value => value !== '--');
if (args.some(value => value.startsWith('-'))) throw new Error('Pass literal Markdown file paths');
async function walk(folder, recursive) {
  const result = [];
  for (const entry of await fs.readdir(folder, {withFileTypes:true})) {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory() && recursive) result.push(...await walk(file, true));
    else if (entry.isFile() && entry.name.endsWith('.md')) result.push(file);
  }
  return result;
}
const files = args.length ? args.map(value => path.resolve(value)) : [...await walk(root, false), ...await walk(path.join(root, 'docs'), true)];
for (const file of files) {
  if (!file.startsWith(root + path.sep) || !(await fs.lstat(file)).isFile() || !file.endsWith('.md')) throw new Error('Only repository Markdown files are accepted');
}
const result = await lint({files,config});
let failures = 0;
for (const [file, errors] of Object.entries(result)) for (const error of errors) {
  console.error(`${path.relative(root,file)}:${error.lineNumber} ${error.ruleNames[0]} ${error.ruleDescription}`);
  failures++;
}
process.exitCode = failures ? 1 : 0;
