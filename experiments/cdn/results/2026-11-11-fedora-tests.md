# Local Fedora verification, 11 November 2026

These commands ran on the user's local Fedora machine through T3 Code, not Claude Code Cloud.

- Host: `fedora`; architecture: `x86_64`; CPU: AMD Ryzen 7 5800H with Radeon Graphics.
- OS: `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`; Python: 3.12.13.
- Checkout: `dee13ff0b52d90f3116cbca1e53f0f166cbc6932`.
- `uv run --locked pytest --cov=pyrail --cov-report=term-missing:skip-covered`: **180 passed**, 9 live tests excluded, **99.08% total coverage**, 4.08 s.
- `uv run --locked python -m unittest discover -s experiments/cdn -p 'test_*.py'`: **7 passed**, 0.006 s.

The reader/GTFS-RT and planner benchmarks were also rerun locally, sequentially after the tests:

```bash
uv run --locked --group experiments python experiments/cdn/compare_all.py data --write experiments/cdn/results/2026-11-11-fedora-readers.md
uv run --with numpy==2.5.4 python experiments/cdn/planner_benchmark.py data --numpy --write experiments/cdn/results/2026-11-11-fedora-planner.json
```

See [reader results](2026-11-11-fedora-readers.md) and [raw planner results](2026-11-11-fedora-planner.json). The snapshot is release `nmbs-sncb-20261111-5c05082d`, with twelve sampled connection pages from 12 November 2026. All readers that can open the files agree with PyArrow; nanoarrow still rejects the CDN file layout. Planner assertions check early-stop/full-scan equivalence, arrive-by feasibility and NumPy/tuple arrival equivalence.

This is x86_64 evidence. Raspberry Pi / Home Assistant-class hardware remains unavailable; the nine live API tests were not run.
