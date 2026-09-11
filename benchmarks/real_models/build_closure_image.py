#!/usr/bin/env python3

from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[2]

OUT = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "linkedin_assets"
)

OUT.mkdir(
    parents=True,
    exist_ok=True
)


fig, ax = plt.subplots(
    figsize=(16, 9)
)

ax.axis("off")


ax.text(
    0.5,
    0.92,
    "AccelClosure — Agentic Timing Closure",
    ha="center",
    va="center",
    fontsize=28,
    fontweight="bold",
    transform=ax.transAxes
)

ax.text(
    0.5,
    0.855,
    "8×8 INT8 Weight-Stationary Systolic Array • Sky130 • 200 MHz Target",
    ha="center",
    va="center",
    fontsize=16,
    transform=ax.transAxes
)


# Initial implementation
ax.text(
    0.18,
    0.60,
    (
        "INITIAL IMPLEMENTATION\n\n"
        "Single-stage PE MAC\n"
        "No input boundary pipeline\n\n"
        "Target: 200 MHz\n"
        "WNS: −2.19 ns\n"
        "TNS: −1204.35 ns\n"
        "Fmax est.: 144.41 MHz\n\n"
        "TIMING FAILED"
    ),
    ha="center",
    va="center",
    fontsize=15,
    transform=ax.transAxes,
    bbox=dict(
        boxstyle="round,pad=1.0",
        linewidth=2
    )
)


# Agent decision
ax.text(
    0.50,
    0.60,
    (
        "AGENT DIAGNOSIS\n\n"
        "Critical path:\n"
        "input → PE MAC register\n\n"
        "Architecture change:\n"
        "• boundary registers\n"
        "• multiply stage\n"
        "• pipeline register\n"
        "• accumulation stage\n"
        "• registered PE hops\n\n"
        "Clock target NOT relaxed"
    ),
    ha="center",
    va="center",
    fontsize=14,
    transform=ax.transAxes,
    bbox=dict(
        boxstyle="round,pad=1.0",
        linewidth=2
    )
)


# Final implementation
ax.text(
    0.82,
    0.60,
    (
        "CLOSED IMPLEMENTATION\n\n"
        "2-stage pipelined PE\n"
        "Registered boundaries + hops\n\n"
        "Verification: 26/26 PASS\n"
        "Target: 200 MHz\n"
        "Worst setup slack: +0.28 ns\n"
        "Setup violations: 0\n"
        "Hold violations: 0\n"
        "Fmax est.: 212.00 MHz\n\n"
        "POST-ROUTE CLOSED"
    ),
    ha="center",
    va="center",
    fontsize=14,
    transform=ax.transAxes,
    bbox=dict(
        boxstyle="round,pad=1.0",
        linewidth=2
    )
)


ax.annotate(
    "",
    xy=(0.36, 0.60),
    xytext=(0.31, 0.60),
    xycoords=ax.transAxes,
    arrowprops=dict(
        arrowstyle="->",
        linewidth=3
    )
)

ax.annotate(
    "",
    xy=(0.69, 0.60),
    xytext=(0.64, 0.60),
    xycoords=ax.transAxes,
    arrowprops=dict(
        arrowstyle="->",
        linewidth=3
    )
)


ax.text(
    0.5,
    0.15,
    (
        "Measured EDA feedback → failure classification → "
        "architecture redesign → functional re-verification → physical closure"
    ),
    ha="center",
    va="center",
    fontsize=16,
    transform=ax.transAxes
)

ax.text(
    0.5,
    0.085,
    (
        "Fmax values are STA estimates. "
        "Generated GDS is physical-design evidence, not foundry signoff."
    ),
    ha="center",
    va="center",
    fontsize=11,
    transform=ax.transAxes
)


path = (
    OUT
    / "03_agentic_timing_closure.png"
)

fig.savefig(
    path,
    dpi=200,
    bbox_inches="tight"
)

plt.close(fig)

print("AGENTIC_CLOSURE_IMAGE=PASS")
print(
    path.relative_to(ROOT)
)
