"""Render both recorded batches; run with uv run --with matplotlib==3.10.0."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

output = Path(__file__).resolve().parent
first = output.parent / "cache-size-matrix-2026-11-14"
sources = [first, output]
batches = [
    {
        "summary": json.loads((source / "summary.json").read_text()),
        "transfer": json.loads((source / "transfer-metrics.json").read_text()),
    }
    for source in sources
]
sizes = [20, 24, 32, 64, 96, 400, 1024, 2048, 3072, 4096]
for batch in batches:
    assert [row["payload_mib"] for row in batch["summary"]["sizes"]] == sizes
    assert [row["payload_mib"] for row in batch["transfer"]["sizes"]] == sizes
    assert len(batch["summary"]["samples"]) == 30
    assert all(row["valid_samples"] == 3 for row in batch["summary"]["sizes"])

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"})
fig, axes = plt.subplots(1, 3, figsize=(16, 8.8), sharey=True)
fig.subplots_adjust(left=0.075, right=0.985, bottom=0.22, top=0.77, wspace=0.17)
colors = ["#52657D", "#087F8C"]
labels = ["First run · attempt 1", "Rerun · attempt 2"]
y = np.arange(len(sizes))
panels = [
    ("summary", "save_seconds", "Complete cache save", "Seconds · lower is faster", 35, [0, 10, 20, 30], 0),
    ("summary", "restore_seconds", "Complete cache restore", "Seconds · lower is faster", 55, [0, 10, 20, 30, 40, 50], 0),
    ("transfer", "upload_mib_per_second", "SDK upload speed", "MiB/s · higher is faster", 700, [0, 200, 400, 600], 1),
]
for ax, (source, key, title, xlabel, limit, ticks, digits) in zip(axes, panels):
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    for index, batch in enumerate(batches):
        rows = [row[key] for row in batch[source]["sizes"]]
        values = np.array([row["median"] for row in rows])
        low = np.array([row["min"] for row in rows])
        high = np.array([row["max"] for row in rows])
        assert np.all(0 <= low) and np.all(low <= values) and np.all(values <= high)
        assert np.max(high) < limit * 0.92
        positions = y + (-0.19 if index == 0 else 0.19)
        ax.barh(positions, values, height=0.31, color=colors[index], label=labels[index])
        ax.errorbar(values, positions, xerr=np.vstack([values - low, high - values]),
                    fmt="none", ecolor="#253243", elinewidth=0.9, capsize=2, capthick=0.9)
        for position, value, maximum in zip(positions, values, high):
            ax.text(maximum + limit * 0.017, position, f"{value:.{digits}f}",
                    va="center", ha="left", fontsize=10, color="#172033")
    ax.set_xlim(0, limit)
    ax.set_xticks(ticks)
    ax.set_xlabel(xlabel, labelpad=14, color="#475569")
    ax.set_title(title, loc="left", pad=19, fontsize=14, weight="bold", color="#172033")
    ax.set_yticks(y, [f"{size // 1024} GiB" if size >= 1024 else f"{size} MiB" for size in sizes])
    ax.tick_params(axis="both", length=0, labelcolor="#475569", pad=8)
    for spine in ax.spines.values():
        spine.set_visible(False)
axes[0].invert_yaxis()
fig.text(0.075, 0.94, "Cache benchmarks: first run vs rerun", fontsize=23, weight="bold", color="#172033")
fig.text(0.075, 0.897, "Celesto Large · 10 payload sizes · 3 repetitions per size in each batch · 30/30 passed in both batches",
         fontsize=12, color="#475569")
fig.legend(handles=[Patch(color=color, label=label) for color, label in zip(colors, labels)],
           loc="upper left", bbox_to_anchor=(0.071, 0.875), ncol=2, frameon=False, handlelength=1.6, columnspacing=2.5)
fig.text(0.075, 0.092, "Bars and labels: medians of 3 runs. Whiskers: minimum to maximum. Each panel starts at zero.",
         fontsize=11, color="#475569")
fig.text(0.075, 0.061, "Save/restore: complete action steps, 1-second resolution. Upload: rounded SDK progress averages; small-file readings are coarse.",
         fontsize=10, color="#475569")
fig.text(0.075, 0.031, "Separate batches on deployed runners. Timing differences do not establish their cause. Source: GitHub Actions run 43530675306, attempts 1 and 2.",
         fontsize=10, color="#475569")
for extension in ["svg", "png"]:
    fig.savefig(output / f"comparison.{extension}", dpi=150, facecolor="white",
                metadata={"Title": "Cache benchmark comparison: attempts 1 and 2"})
plt.close(fig)
svg_path = output / "comparison.svg"
svg = svg_path.read_text().replace('<svg ', '<svg role="img" aria-labelledby="chart-title chart-desc" ', 1)
svg = svg.replace(' <metadata>',
                  ' <title id="chart-title">Cache benchmarks: first run versus rerun</title>\n'
                  ' <desc id="chart-desc">Grouped bars compare save time, restore time and SDK upload speed for ten payload sizes from 20 MiB to 4 GiB. Bars are three-run medians; whiskers show minimum and maximum. At 4 GiB, save is 22 versus 18 seconds, restore 41 versus 29 seconds, and upload speed 408.3 versus 582.2 MiB/s. Exact values for all sizes are in the adjacent report tables.</desc>\n <metadata>', 1)
svg_path.write_text(svg)
print(f"Rendered {output / 'comparison.svg'} and comparison.png from the two saved batches.")
