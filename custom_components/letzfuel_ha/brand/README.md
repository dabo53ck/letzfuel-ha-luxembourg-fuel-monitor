# Brand assets

The mark: a fuel droplet in the Luxembourg flag colours (red / white / light blue)
holding a speedometer needle — "Luxembourg fuel, read live".

| Light | Dark | |
| --- | --- | --- |
| `icon.png` (256) / `icon@2x.png` (512) | `dark_icon.png` / `dark_icon@2x.png` | Square app icon |
| `logo.png` / `logo@2x.png` | `dark_logo.png` / `dark_logo@2x.png` | Wordmark ("LëtzFuel HA" + descriptor) |

Each has a matching `*.svg` source. Home Assistant (2026.3+) loads these directly
from this folder — no `home-assistant/brands` PR needed — and picks the `dark_*`
variant in dark mode.

The PNGs are committed, rendered from the SVGs with
[resvg](https://github.com/RazrFalcon/resvg). Regenerate after editing an SVG:

```sh
for v in icon dark_icon; do
  resvg -w 256 -h 256 "$v.svg" "$v.png"
  resvg -w 512 -h 512 "$v.svg" "$v@2x.png"
done
for v in logo dark_logo; do
  resvg -h 256 "$v.svg" "$v.png"
  resvg -h 512 "$v.svg" "$v@2x.png"
done
```

The `logo` PNGs use whatever bold sans the renderer finds (the SVG asks for
Bricolage Grotesque, then falls back) — fine for the README / HACS card. For a
`home-assistant/brands` PR (only needed for HA < 2026.3 or the public HACS store),
convert the `<text>` to outlines first (Inkscape: *Path → Object to Path*).
