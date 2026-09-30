# Bloody Math: Algebra Quest — Web Edition

Browser port of Bloody Math v1.6.0, intended for Chrome/Chromium and ChromeOS via Pygbag + GitHub Pages.

## Local build

```bash
python3 -m pip install --upgrade pygbag
python3 -m pygbag --build --title "Bloody Math: Algebra Quest" game
```

The generated site is under `game/build/web/`.

## GitHub Pages

The included GitHub Actions workflow builds the Pygbag version and deploys `game/build/web/` to GitHub Pages whenever `main` changes.

## Notes

- Gameplay content is based on Bloody Math v1.6.0.
- Browser audio uses OGG assets.
- The desktop Linux `.deb` remains the reference build; this web port is a separate target.
