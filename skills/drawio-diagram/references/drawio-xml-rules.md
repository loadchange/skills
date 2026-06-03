# draw.io XML rules (reference)

You generate **only `mxCell` elements**. The wrapper (`<mxfile>`,
`<mxGraphModel>`, `<root>`) and the root cells (`id="0"`, `id="1"`) are added
automatically by `drawio-ai apply`.

## Structure rules (XML is rejected if violated)
1. Generate ONLY `mxCell` elements — NO wrapper tags, NO root cells.
2. All `mxCell` elements are SIBLINGS — never nest an `mxCell` inside another.
3. Unique sequential ids starting from `"2"`.
4. `parent="1"` for top-level shapes, or `parent="<container-id>"` when grouped
   (e.g. a node inside a swimlane uses the swimlane's id as parent).
5. Edge `source`/`target` must reference existing cell ids.
6. Escape special chars in `value`: `&lt;` `&gt;` `&amp;` `&quot;`.
7. NEVER include XML comments (`<!-- -->`) — draw.io strips them and breaks edits.

## Shape (vertex)
```xml
<mxCell id="2" value="Label" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>
</mxCell>
```

## Connector (edge)
```xml
<mxCell id="3" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="4">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

## Swimlane / container + child + edge
```xml
<mxCell id="lane1" value="Frontend" style="swimlane;" vertex="1" parent="1">
  <mxGeometry x="40" y="40" width="200" height="200" as="geometry"/>
</mxCell>
<mxCell id="step1" value="Step 1" style="rounded=1;" vertex="1" parent="lane1">
  <mxGeometry x="20" y="60" width="160" height="40" as="geometry"/>
</mxCell>
<mxCell id="edge1" style="edgeStyle=orthogonalEdgeStyle;endArrow=classic;" edge="1" parent="1" source="step1" target="step2">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

## Layout constraints
- Keep everything on one page: `x` in 0–800, `y` in 0–600.
- Max container width 700, height 550. Start margins around `x=40, y=40`.
- Compact grid/stack layouts; don't spread elements across page breaks.

## Edge routing (avoid overlaps)
1. Two edges between the same pair of nodes MUST use different exit/entry points
   (e.g. `exitY=0.3` vs `exitY=0.7`) — never the same path.
2. Bidirectional (A↔B): use opposite sides. A→B exit right (`exitX=1`) enter left
   (`entryX=0`); B→A exit left enter right.
3. Set `exitX/exitY/entryX/entryY` explicitly on edges.
4. Route edges AROUND intermediate shapes using 1–3 waypoints (orthogonal L/U
   paths). For diagonal connections, route along the diagram perimeter, not
   through the middle where other shapes sit.
5. Avoid corner connection points (both X and Y at 0 or 1) — pick the side facing
   the flow (`exitY=1`/`entryY=0` for top-to-bottom, `exitX=1`/`entryX=0` for
   left-to-right).

### Waypoint example (route around an obstacle)
```xml
<mxCell id="e" style="edgeStyle=orthogonalEdgeStyle;exitX=0.5;exitY=0;entryX=1;entryY=0.5;endArrow=classic;" edge="1" parent="1" source="hotfix" target="main">
  <mxGeometry relative="1" as="geometry">
    <Array as="points">
      <mxPoint x="750" y="80"/>
      <mxPoint x="750" y="150"/>
    </Array>
  </mxGeometry>
</mxCell>
```

## Common styles
- Shapes: `rounded=1`, `fillColor=#hex`, `strokeColor=#hex`, `whiteSpace=wrap;html=1;`
- Edges: `endArrow=classic|block|open|none`, `curved=1`, `edgeStyle=orthogonalEdgeStyle`
- Text: `fontSize=14`, `fontStyle=1` (bold), `align=center|left|right`
- Animated connector: add `flowAnimation=1` to the edge style.
- Container shapes that hold children: add `fillColor=none;` so they don't cover
  what's inside.

## Cloud / icon libraries
For AWS/Azure/GCP/Kubernetes/Cisco/Material/etc., the exact `shape=...` style
strings are documented per library in the repo's `docs/shape-libraries/*.md`
(e.g. `aws4.md`, `azure2.md`, `gcp2.md`, `kubernetes.md`). Look up the syntax —
never guess icon style strings. For AWS use the 2025 icon set.
