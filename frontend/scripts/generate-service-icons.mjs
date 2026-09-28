#!/usr/bin/env node
/**
 * Build the bundled service logos in public/service-icons/.
 *
 *   npm i --no-save simple-icons@16.33.0
 *   node scripts/generate-service-icons.mjs node_modules/simple-icons
 *
 * Input: backend/apps/catalog/service_icons.json (our service slug -> Simple
 * Icons slug) and the Simple Icons package (CC0-1.0). Output: one SVG per
 * service, named by OUR slug so the backend can point at /service-icons/<slug>.svg,
 * plus SOURCES.json recording where every mark came from and under what licence.
 *
 * Each file is a complete tile - the brand's colour with its mark on top, like
 * an app icon - so it reads the same on any background and the frontend only
 * ever renders an <img>. Nothing here is fetched at runtime.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const pkg = resolve(process.argv[2] ?? join(here, "..", "node_modules", "simple-icons"));
const mappingPath = resolve(here, "..", "..", "backend", "apps", "catalog", "service_icons.json");
const outDir = resolve(here, "..", "public", "service-icons");

if (!existsSync(join(pkg, "data", "simple-icons.json"))) {
  console.error(`simple-icons not found at ${pkg}`);
  process.exit(1);
}

const version = JSON.parse(readFileSync(join(pkg, "package.json"), "utf8")).version;
const data = JSON.parse(readFileSync(join(pkg, "data", "simple-icons.json"), "utf8"));
const bySlug = new Map(data.map((icon) => [icon.slug, icon]));
const mapping = JSON.parse(readFileSync(mappingPath, "utf8")).icons;

/** Relative luminance, 0 (black) to 1 (white). */
function luminance(hex) {
  const channel = (i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

function escapeXml(text) {
  return text.replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[c]);
}

mkdirSync(outDir, { recursive: true });
const sources = {};
const problems = [];

for (const [serviceSlug, iconSlug] of Object.entries(mapping)) {
  const icon = bySlug.get(iconSlug);
  const file = join(pkg, "icons", `${iconSlug}.svg`);
  if (!icon || !existsSync(file)) {
    problems.push(`${serviceSlug}: no Simple Icons entry "${iconSlug}"`);
    continue;
  }
  const path = readFileSync(file, "utf8").match(/<path d="([^"]+)"/)?.[1];
  if (!path) {
    problems.push(`${serviceSlug}: could not read the path of "${iconSlug}"`);
    continue;
  }

  const hex = icon.hex.toUpperCase();
  const light = luminance(hex);
  // A near-white brand gets a white tile with a hairline; a light one a dark
  // mark; everything else a white mark. Never white on white.
  const tile = light > 0.9 ? "FFFFFF" : hex;
  const mark = light > 0.9 ? "111111" : light > 0.55 ? "111111" : "FFFFFF";
  const border = light > 0.9 ? ` stroke="#E4E7EC" stroke-width="1"` : "";

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" role="img" aria-label="${escapeXml(icon.title)} logo">` +
    `<title>${escapeXml(icon.title)} logo</title>` +
    `<rect x="0.5" y="0.5" width="47" height="47" rx="11" fill="#${tile}"${border}/>` +
    `<path transform="translate(11 11) scale(1.0833)" fill="#${mark}" d="${path}"/>` +
    `</svg>\n`;
  writeFileSync(join(outDir, `${serviceSlug}.svg`), svg);

  sources[serviceSlug] = {
    title: icon.title,
    simple_icons_slug: iconSlug,
    brand_hex: hex,
    source: icon.source,
    license: icon.license ?? "CC0-1.0 (Simple Icons)",
    guidelines: icon.guidelines ?? null,
  };
}

writeFileSync(
  join(outDir, "SOURCES.json"),
  JSON.stringify(
    {
      generated_by: "frontend/scripts/generate-service-icons.mjs",
      library: `simple-icons@${version}`,
      library_license: "CC0-1.0",
      note: "Trademarks belong to their owners. Marks are used only to identify the service a number is for.",
      icons: sources,
    },
    null,
    2,
  ) + "\n",
);

console.log(`wrote ${Object.keys(sources).length} icons to ${outDir}`);
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
