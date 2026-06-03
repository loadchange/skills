---
name: drawio-diagram
description: >
  Create or edit draw.io / diagrams.net diagrams and write a .drawio file. Use whenever the
  user asks to draw, diagram, chart, or visualize something — flowcharts, architecture/cloud
  diagrams (AWS/Azure/GCP/K8s), sequence diagrams, ER diagrams, mind maps, org charts,
  network diagrams — or to modify/add to/fix an existing .drawio file. Triggers on "画个图/
  流程图/架构图/时序图/思维导图", "draw a diagram", "make a flowchart", "diagram this". You
  generate the draw.io XML yourself and a bundled zero-dependency script wraps it into a
  .drawio file. No external AI model or API key is used.
---

# draw.io Diagram

You are the diagram generator. You write the draw.io `mxCell` XML directly, then a small
bundled Node script wraps it into a `.drawio` file the user opens in draw.io / diagrams.net.
**Do not call any other AI model or MCP server** — you are the brain here.

Reply in the same language as the user. Keep prose short — the artifact is the diagram.

## Workflow — NEW diagram

1. Read `<skill-path>/references/drawio-xml-rules.md` and follow it. You generate **only
   `mxCell` elements** — no `<mxfile>`, `<mxGraphModel>`, `<root>`, and no root cells
   (id="0"/id="1"). The script adds those.
2. `Write` your mxCell XML to a temp file, e.g. `cells.xml`.
3. Wrap it into a `.drawio` file:
   ```bash
   node <skill-path>/scripts/drawio-wrap.mjs --file cells.xml -o diagram.drawio
   ```
   (Or pipe via stdin: `cat cells.xml | node <skill-path>/scripts/drawio-wrap.mjs -o diagram.drawio`.)
   The script needs only Node — no `npm install`.
4. Tell the user the output path. You may delete the temp `cells.xml`.

## Workflow — EDIT an existing diagram

The wrap script handles boilerplate, not edits. To modify an existing `.drawio`:

1. `Read` the `.drawio` file to see the current `mxCell` elements and their ids.
2. Edit the XML **directly** with the `Edit`/`Write` tools:
   - Change a label/style → edit that `mxCell`'s attributes in place.
   - Add a shape/edge → insert a new `<mxCell>` with a unique id before `</root>`.
   - Delete a shape → remove its `<mxCell>` **and** any edges whose `source`/`target`
     reference its id (and any child cells whose `parent` is its id).
3. Keep the `<mxfile>…</mxfile>` wrapper intact. If you'd rather regenerate from scratch,
   produce fresh mxCells and re-run the wrap script (step 3 above) to overwrite the file.

## Rules that matter most

- NEW diagrams: ONLY `mxCell` elements; siblings, never nested; unique ids from "2";
  `parent="1"` for top-level (or a container id for grouped shapes).
- Escape `&lt; &gt; &amp; &quot;` in attribute values. No XML comments (`<!-- -->`).
- Keep within one page: x in 0–800, y in 0–600.
- Follow the edge-routing rules in the reference so connectors don't overlap shapes or
  each other (different exit/entry points, waypoints around obstacles, no corner anchors).
- For cloud/tech icons (AWS/Azure/GCP/K8s/Cisco/Material…), use the correct `shape=…` style
  string. If unsure of exact icon syntax, say so rather than guessing — guessed icon styles
  render as blank boxes.

## Quick reference: minimal valid pieces

Shape: `<mxCell id="2" value="Box" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="120" height="60" as="geometry"/></mxCell>`

Edge: `<mxCell id="3" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="4"><mxGeometry relative="1" as="geometry"/></mxCell>`

See `references/drawio-xml-rules.md` for swimlanes, waypoints, styles, and the full
edge-routing rules.
