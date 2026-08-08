/**
 * Render D2 source to SVG, or check that it compiles.
 *
 *   node scripts/d2render.mjs <input.d2> <output.svg> [layout]
 *   node scripts/d2render.mjs <input.d2> --check
 *
 * The published `@terrastruct/d2` package is a WASM library rather than a CLI, so
 * this is the shim the Python side shells out to. That turns out to be better than
 * a platform binary: WASM runs wherever Node does, and it is vendored into
 * node_modules like mermaid-cli, so a job never needs the network.
 *
 * Compiling *is* the validation. The Mermaid path had only a best-effort regex,
 * which is why invalid diagrams reached readers; here the real parser decides.
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { D2 } from '@terrastruct/d2'

const [, , inputPath, outputPath, layout = 'dagre'] = process.argv

if (!inputPath || !outputPath) {
  console.error('usage: d2render.mjs <input.d2> <output.svg|--check> [dagre|elk]')
  process.exit(2)
}

const source = readFileSync(inputPath, 'utf8')
const d2 = new D2()

try {
  const result = await d2.compile(source, { layout })

  if (outputPath === '--check') {
    process.exit(0)
  }

  const svg = await d2.render(result.diagram, {
    ...result.renderOptions,
    // Embedded in HTML and in a data: URI, so the XML preamble is noise.
    noXMLTag: true,
    pad: 20,
  })
  writeFileSync(outputPath, svg, 'utf8')
  process.exit(0)
} catch (error) {
  console.error(String(error?.message ?? error))
  process.exit(1)
}
