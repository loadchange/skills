# Image and video generation through Grok

Grok Build carries the xAI **Imagine** models as ordinary client-side tools, so
they work over ACP exactly like any other tool call. Unlike `x_search` (which runs
server-side and returns only prose), these write a real file to disk and return
its path.

## The four tools

| Tool | Input | Produces |
|---|---|---|
| `image_gen` | `{prompt, aspect_ratio}` | New image from text |
| `image_edit` | `{prompt, image: [refs], aspect_ratio}` | Edited / restyled / remixed image |
| `image_to_video` | `{image, prompt?, duration?, resolution_name?}` | Video animating one image |
| `reference_to_video` | `{prompt, images: [2–7], aspect_ratio?, duration?, resolution_name?}` | Video blending several references |

Default image model is `grok-imagine-image-quality`. All four require a
SuperGrok-tier account; on free / X Basic the tool returns an upgrade notice
instead of a file and the script exits non-zero.

**Aspect ratios**: `1:1` `16:9` `9:16` `4:3` `3:4` `3:2` `2:3` `2:1` `1:2`
`19.5:9` `9:19.5` `20:9` `9:20` `auto`. For a single-image `edit` the ratio is
ignored — the output matches the input.

**Image references** for `edit` / `video` resolve in this order: an absolute
filesystem path, or a `data:image/...;base64,...` URL. Relative paths will not
resolve — the tool runs with the isolated scratch workspace as its cwd, not yours.

## Where files land

Grok saves into its session folder:

```
~/.grok/sessions/<url-encoded-cwd>/<session-id>/images/1.jpg
~/.grok/sessions/<url-encoded-cwd>/<session-id>/videos/1.mp4
```

That path is not something to hand to a user. The script reads the
`rawOutput` of each media tool call — `{type, path, filename, session_folder}` —
and copies the file to `--out`:

- `--out ./assets` → `./assets/grok-image.jpg`, colliding names get `-2`, `-3`, …
- `--out ./logo.jpg` (single result, has a suffix) → exactly that filename
- Default `--out .` → the current directory

Naming per kind: `grok-image` (`image_gen`), `grok-edit` (`image_edit`),
`grok-video` (both video tools).

## Prompting

Give a **brief**, not a finished prompt. Grok loads xAI's own `imagine` skill and
expands it — one measured example:

> brief: `a minimalist origami paper crane logo, flat vector, dark background`
>
> what Grok sent: *"Minimalist origami paper crane logo mark, flat vector
> illustration, single stylized crane formed from clean geometric folded-paper
> planes and sharp crease lines, centered composition, balanced negative space,
> simple iconic silhouette readable at small size, limited palette of soft white
> and pale cream paper tones with subtle cool gray crease edges, solid deep
> charcoal-black background, no gradients, no texture noise, no photorealism, no
> drop shadows, crisp edges, modern brand identity logo style, high contrast,
> uncluttered, professional graphic design"*

Do state hard constraints — they are preserved: aspect ratio, exact colours,
"keep the same composition", "no text". For edits, saying what must *not* change
matters as much as what should.

**Use code, not Imagine, when the content must be exact.** Image models garble
text, invent numbers, and draw chart bars matching no data. Charts, labelled
diagrams, tables, and UI mockups with real copy belong in HTML/CSS or a plotting
library. Imagine is for photos, illustrations, characters, scenes, and decorative
art — where only the look matters.

## Recipes

```bash
S=<skill-path>/scripts/grok_acp.py

# Logo / icon
python3 $S image "minimalist origami crane logo, flat vector, dark background" \
  --aspect 1:1 --out ./assets/logo.jpg

# Hero image
python3 $S image "wide cinematic shot of a data centre at dusk, cool blue light" \
  --aspect 16:9 --out ./public/hero.jpg

# Recolour, composition locked
python3 $S edit "make the crane warm gold, keep the exact composition and background" \
  --image "$PWD/assets/logo.jpg" --out ./assets/logo-gold.jpg

# Multi-reference blend
python3 $S edit "combine the subject of the first with the palette of the second" \
  --image "$PWD/a.jpg" --image "$PWD/b.jpg" --aspect 16:9

# Animate a still
python3 $S video "slow push-in, subtle shimmer on the gold paper" \
  --image "$PWD/assets/logo-gold.jpg" --duration 6 --resolution 480p

# Machine-readable result
python3 $S image "app icon, rounded square, teal gradient" --aspect 1:1 --json
# -> .media[0].saved holds the final path
```

## Known limits

- **Video fails on Zero Data Retention accounts.** The API rejects it with:

  ```
  HTTP 400: {"code":"invalid-argument",
   "error":"Zero Data Retention teams must provide output.upload_url for video generation."}
  ```

  ZDR accounts cannot have video stored server-side, so the output must go to a
  presigned URL you own. Fix it in `~/.grok/config.toml`:

  ```toml
  [tools.zdr_video_output_s3]
  bucket = "your-bucket"
  endpoint = "https://s3.example.com"
  region = "us-east-1"
  # key_prefix = "grok-videos/"   # default
  # expires_secs = 900            # default
  read_write = { access_key_id = "...", secret_access_key = "..." }
  ```

  Image generation is unaffected. When video does route through S3, the result
  comes back as `uploaded_url` with no local file — the script prints the URL and
  says it was not saved locally.
- **One call per run.** The rules tell Grok to make exactly one generation call
  unless you ask for variants, so a run costs one image. Ask for "three variants"
  explicitly if you want more.
- **No file is silently faked.** If the tool errors, the script prints the error
  verbatim and exits 1 rather than reporting a path.
- **`image_gen` never sees your repo.** It runs in the scratch workspace; pass
  absolute paths for any input image.
