# Brand assets (staged for home-assistant/brands)

Home Assistant doesn't read integration icons from the integration's own repo —
it pulls them from the community-maintained
[`home-assistant/brands`](https://github.com/home-assistant/brands) repo, keyed
by domain. To make the DISH logo show up in the HA UI and HACS, these files
need to be submitted there as a pull request, under
`custom_integrations/dish_receiver/`.

## What's here

`custom_integrations/dish_receiver/` is laid out exactly as that repo expects,
so it can be copied straight into a fork:

| File | Size | Spec |
|---|---|---|
| `icon.png` | 256×256 | square icon |
| `icon@2x.png` | 512×512 | square icon, hDPI |
| `logo.png` | 676×256 | landscape logo, 256px height |
| `logo@2x.png` | 1351×512 | landscape logo, hDPI |

All PNG, transparent background, trimmed, optimized.

## Source

DISH's current wordmark (in use since 2019), from Wikimedia Commons:
`https://commons.wikimedia.org/wiki/File:Dish_Network_2019.svg` — the same
sourcing approach (official/public brand marks via Wikimedia Commons or press
kits) used throughout the `home-assistant/brands` repo for third-party
integrations that talk to a branded product or service.

## Submitting

1. Fork `home-assistant/brands`.
2. Copy `custom_integrations/dish_receiver/` into the fork at the same path.
3. Open a PR. Their CI validates dimensions/format automatically.
4. Once merged, the icon appears in HA/HACS for the `dish_receiver` domain —
   no change needed on the integration side.
