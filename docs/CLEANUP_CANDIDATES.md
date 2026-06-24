# Cleanup Candidates

These files/directories are generated runtime or build-session residue and should stay out of source control. They were **not deleted** during the safe implementation pass.

- `.radar-data/` — preserved SQLite state, reports, logs, previews.
- `.pytest_cache/` — pytest cache.
- `src/radar/__pycache__/` and `tests/__pycache__/` — Python bytecode.
- `src/competitor_content_radar.egg-info/` — editable-install metadata.
- `_write_part1.py`, `_run_part2.py`, `_write_part3.py`, `_write_part4.py`, `_write_part5.py`, `_write_tests.py` — generated writer scaffolding from the initial build.
- `%SystemDrive%/ProgramData/Microsoft/Windows/Caches/` — project-root Windows cache residue observed after a Hermes smoke test. Do not delete without operator approval; likely caused by literal environment/path expansion into the working directory.

Operator cleanup can remove these after confirming no preserved run artifacts are needed. The active source files, docs, tests, scripts, config example, and PRD are outside this list.
