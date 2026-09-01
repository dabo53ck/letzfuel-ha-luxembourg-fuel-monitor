# Brand assets

The mark: a fuel droplet in the Luxembourg flag colours (red / white / light blue)
holding a speedometer needle — "Luxembourg fuel, read live".

| File | |
| --- | --- |
| `icon.svg` / `icon.png` (256) / `icon@2x.png` (512) | Square app icon |
| `logo.svg` / `logo.png` / `logo@2x.png` | Wordmark ("LëtzFuel HA" + descriptor) |

The PNGs are committed and were rendered from the SVGs with
[resvg](https://github.com/RazrFalcon/resvg). Regenerate after editing an SVG:

```sh
resvg -w 256 -h 256 icon.svg icon.png
resvg -w 512 -h 512 icon.svg icon@2x.png
resvg -h 256        logo.svg logo.png
resvg -h 512        logo.svg logo@2x.png
```

`logo.png` uses whatever bold sans the renderer finds (the SVG asks for Bricolage
Grotesque, then falls back); good enough for the README / HACS card.

## Getting the icon into the Home Assistant UI

Home Assistant loads integration icons **only** from
[`home-assistant/brands`](https://github.com/home-assistant/brands). Open a PR there
adding `icon.png` + `icon@2x.png` (and `logo.png` / `logo@2x.png`) under
`custom_integrations/letzfuel_ha/`. Until it merges, the device page just shows the
default puzzle-piece icon.
