# S3 rendered samples

Produced offline by `python3 scripts/eval_s3.py --samples` (corpus deck build, LibreOffice to PDF, `pdftoppm -r 80`).
All figures are synthetic; project names are fictional. No live model was used, so the critic did not run.

| File | Shows |
|---|---|
| `04-sell-side-pitchbook.pptx`, `04-sell-side-pitchbook-01.png` to `-10.png` | English 10-slide sell-side pitchbook section (Project Falcon): exec summary, KPI row, combo chart, comps table, precedents, buyer matrix, process flow |
| `05-ic-dental-platform.pptx`, `05-ic-dental-platform-01.png` to `-10.png` | English 10-slide investment committee memo (Project Meridian): value bridge waterfall, IRR sensitivity, risk heatmap, decision box |
| `14-ar-saudi-ipo-readiness.pptx`, `14-ar-saudi-ipo-readiness-01.png` to `-10.png` | Arabic (RTL) 10-slide IPO readiness deck: mirrored layout, Arabic titles, RTL tables and charts, Gantt |
| `art-editorial_illustration.png` | Art direction: editorial illustration (flat overlapping shapes) |
| `art-isometric_system.png` | Art direction: isometric systems |
| `art-line_art_schematic.png` | Art direction: line-art schematic with nodes and connectors |
| `art-data_art.png` | Art direction: data art (dot fields, ribbons, radial bars) |
| `art-duotone_hero.png` | Art direction: duotone hero |
| `art-annotated_map.png` | Art direction: annotated abstract map |
| `art-iconographic_system.png` | Art direction: iconographic system |
| `art-bold_typographic.png` | Art direction: bold typographic forms (numerals as shapes) |

The art PNGs are the best of three candidates from the offline procedural tier (the image endpoint and the SVG designer need a
live adapter), scored by the deterministic visual scorer. Slide PNGs show the real renderer output, including the generated
cover visual of each deck.
