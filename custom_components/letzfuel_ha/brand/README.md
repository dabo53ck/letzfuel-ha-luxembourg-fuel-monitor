# Brand assets

The mark: a fuel droplet in the Luxembourg flag colours (red / white / light blue)
holding a speedometer needle — "Luxembourg fuel, read live".

| File | Purpose |
| --- | --- |
| `icon.svg` | Source for the square app icon |
| `logo.svg` | Source for the wordmark (outline the text before exporting — see below) |

## Producing the PNGs

Home Assistant loads integration icons **only** from the
[`home-assistant/brands`](https://github.com/home-assistant/brands) repository, as
trimmed transparent PNGs. Generate them (no design tool needed):

```sh
npx svgexport icon.svg icon.png    256:256
npx svgexport icon.svg icon@2x.png 512:512
# wordmark: open logo.svg in Inkscape, Path > Object to Path, save, then
npx svgexport logo.svg logo.png    "svg{}" 1000:280
npx svgexport logo.svg logo@2x.png "svg{}" 2000:560
```

Then open a PR on `home-assistant/brands` adding them under
`custom_integrations/letzfuel_ha/`.

Dropping the same `icon.png` / `icon@2x.png` next to this file also satisfies the
HACS validation action's brand check in the meantime.
