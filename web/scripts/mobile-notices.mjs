import { readdir, readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const modules = path.join(root, "node_modules");
const packages = [];
for (const entry of await readdir(modules, { withFileTypes: true })) {
  if (entry.name.startsWith(".")) continue;
  if (entry.name.startsWith("@")) {
    for (const child of await readdir(path.join(modules, entry.name))) packages.push(path.join(modules, entry.name, child));
  } else if (entry.isDirectory()) packages.push(path.join(modules, entry.name));
}
const notices = ["Cuplik Android — third-party notices.\nMedia3 and AndroidX: Apache License 2.0; https://www.apache.org/licenses/LICENSE-2.0\nWhisper.cpp: MIT; included separately as whisper-LICENSE.txt.\n"];
for (const directory of packages.sort()) {
  try {
    const metadata = JSON.parse(await readFile(path.join(directory, "package.json"), "utf8"));
    for (const file of await readdir(directory)) if (/^(licen[sc]e|notice|ofl)(\.|$)/i.test(file)) {
      const text = await readFile(path.join(directory, file), "utf8");
      notices.push(`\n${metadata.name}@${metadata.version} — ${file}\n${text}`);
    }
  } catch { /* Non-package executable directories are not dependencies. */ }
}
const output = path.join(root, "../android/app/src/main/assets");
await mkdir(output, { recursive: true });
await writeFile(path.join(output, "THIRD_PARTY_NOTICES.txt"), notices.join("\n"));
