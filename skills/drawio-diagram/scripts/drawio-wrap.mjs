#!/usr/bin/env node
/**
 * drawio-wrap — wrap draw.io `mxCell` elements into a complete `.drawio` file.
 *
 * Zero dependencies (Node built-ins only). The agent (Claude Code) generates the
 * `mxCell` XML; this script adds the <mxfile>/<mxGraphModel>/<root> boilerplate
 * and the structural root cells (id="0"/id="1"), strips any wrapper tags the
 * model accidentally included, and writes the file draw.io / diagrams.net opens.
 *
 * Usage:
 *   cat cells.xml | node drawio-wrap.mjs -o diagram.drawio
 *   node drawio-wrap.mjs --file cells.xml -o diagram.drawio
 *   node drawio-wrap.mjs --file cells.xml --stdout
 *
 * Accepts bare mxCells OR a full mxfile (idempotent — re-wrapping is a no-op).
 */
import { readFile, writeFile } from "node:fs/promises"
import process from "node:process"

const ROOT_CELLS = '<mxCell id="0"/><mxCell id="1" parent="0"/>'

function wrapWithMxFile(xml) {
    if (!xml || !xml.trim()) {
        return `<mxfile><diagram name="Page-1" id="page-1"><mxGraphModel><root>${ROOT_CELLS}</root></mxGraphModel></diagram></mxfile>`
    }
    if (xml.includes("<mxfile")) return xml
    if (xml.includes("<mxGraphModel")) {
        return `<mxfile><diagram name="Page-1" id="page-1">${xml}</diagram></mxfile>`
    }
    let content = xml
    if (xml.includes("<root>")) content = xml.replace(/<\/?root>/g, "").trim()

    // Strip trailing wrapper-only tags some models append.
    const lastSelfClose = content.lastIndexOf("/>")
    const lastMxCellClose = content.lastIndexOf("</mxCell>")
    const lastValidEnd = Math.max(lastSelfClose, lastMxCellClose)
    if (lastValidEnd !== -1) {
        const endOffset = lastMxCellClose > lastSelfClose ? 9 : 2
        const suffix = content.slice(lastValidEnd + endOffset)
        if (/^(\s*<\/[^>]+>)*\s*$/.test(suffix)) {
            content = content.slice(0, lastValidEnd + endOffset)
        }
    }
    // Remove any root cells the model wrongly included.
    content = content
        .replace(/<mxCell[^>]*\bid=["']0["'][^>]*(?:\/>|><\/mxCell>)/g, "")
        .replace(/<mxCell[^>]*\bid=["']1["'][^>]*(?:\/>|><\/mxCell>)/g, "")
        .trim()

    return `<mxfile><diagram name="Page-1" id="page-1"><mxGraphModel><root>${ROOT_CELLS}${content}</root></mxGraphModel></diagram></mxfile>`
}

function parseArgs(argv) {
    const a = { out: "diagram.drawio", file: null, stdout: false, help: false }
    for (let i = 0; i < argv.length; i++) {
        const arg = argv[i]
        if (arg === "-o" || arg === "--out") a.out = argv[++i]
        else if (arg === "--file" || arg === "-f") a.file = argv[++i]
        else if (arg === "--stdout") a.stdout = true
        else if (arg === "-h" || arg === "--help") a.help = true
        else {
            process.stderr.write(`Unknown option: ${arg}\n`)
            process.exit(1)
        }
    }
    return a
}

async function readStdin() {
    if (process.stdin.isTTY) return ""
    const chunks = []
    for await (const c of process.stdin) chunks.push(c)
    return Buffer.concat(chunks).toString("utf-8").trim()
}

const HELP = `drawio-wrap — wrap mxCell XML into a .drawio file

  cat cells.xml | node drawio-wrap.mjs -o diagram.drawio
  node drawio-wrap.mjs --file cells.xml -o diagram.drawio
  node drawio-wrap.mjs --file cells.xml --stdout

Options:
  -o, --out <file>   output path (default: diagram.drawio)
  -f, --file <file>  read XML from a file instead of stdin
      --stdout       print the wrapped XML instead of writing a file
  -h, --help         show this help`

async function main() {
    const args = parseArgs(process.argv.slice(2))
    if (args.help) {
        process.stdout.write(`${HELP}\n`)
        return
    }

    let xml = args.file ? await readFile(args.file, "utf-8") : await readStdin()
    xml = (xml || "").trim()

    if (!xml || !xml.includes("<mxCell")) {
        process.stderr.write(
            "Error: no mxCell elements found in input. Provide draw.io mxCell XML via --file or stdin.\n",
        )
        process.exit(1)
    }

    const wrapped = wrapWithMxFile(xml)

    if (args.stdout) {
        process.stdout.write(`${wrapped}\n`)
    } else {
        await writeFile(args.out, wrapped, "utf-8")
        process.stderr.write(`✓ Wrote ${args.out}\n`)
    }
}

main().catch((e) => {
    process.stderr.write(`Fatal: ${e.message}\n`)
    process.exit(1)
})
