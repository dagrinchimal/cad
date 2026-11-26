---
id: plugins
type: concept
title: Adding your own file formats (plugins)
order: 12
synonyms: [plugin, extend, custom format, script, add format]
related: [file-formats, options]
glossary: []
---
Every file format is a plugin, and you can add your own: a Python file placed in your **plugins folder**. Options shows where it is (normally `%APPDATA%\CallingAllDumbies\plugins`, or `data\plugins` beside `CAD.exe` in the portable version). Plugins load when the program starts; Options lists the ones loaded.

A complete, working example (a CSV point list) and the full description of what a plugin can do are in `docs/PLUGINS.md` in the program's source (on GitHub).

Plugins are program code: only add ones you trust.
