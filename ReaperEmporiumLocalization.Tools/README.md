# Reaper Emporium Localization Tools

Small Python helpers for the Reaper Emporium localization workflow.

## Commands

```powershell
python main.py stats data
python main.py install data
python main.py download --progress
python main.py pull --progress
python main.py build-dump
```

`install` discovers package folders such as `data/本体解包` and `data/DLC解包`, merges database JSON files by asset name, merges `dll_strings.json` by original text, and writes the runtime layout used by the BepInEx plugin:

```text
<game root>/localization/
  database/*.json
  dll_strings/dll_strings.json
```

Set `PATH_GAME_ROOT`, `PARATRANZ_PROJECT_ID`, and `PARATRANZ_TOKEN` in `.env` when needed.

`build-dump` reads `data/0-DumpData/MainGame` and `data/0-DumpData/DLCGame`, then writes:

```text
build/dump/
  MainGame/
    database/*.json
    dll_strings.json
  DLCGame/
    database/*.json
    dll_strings.json
```

`MainGame` is copied in full. `DLCGame` database files keep only parsed JSON entries that are not identical to entries in the same MainGame file. DLC `dll_strings.json` compares by key method identity plus entry content, so shifted IL offsets and compiler-generated coroutine numbers do not create duplicate DLC strings. Empty DLC diff files are skipped.
