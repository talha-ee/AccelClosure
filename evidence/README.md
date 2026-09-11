# AccelClosure Experimental Evidence

This directory contains the lightweight experimental evidence used to support the AccelClosure results reported in the project documentation.

## Physically Validated Configurations

| Array | Dataflow | Precision | Target | Post-route Fmax Estimate | Routed Area | Vectorless Power | Status |
|---|---|---|---:|---:|---:|---:|---|
| 4x4 | WS | INT8 | 180 MHz | 210.57 MHz | 0.121669 mm² | 0.0795 W | Physically closed |
| 8x8 | WS | INT8 | 200 MHz | 212.00 MHz | 0.505428 mm² | 0.3570 W | Physically closed |
| 16x16 | WS | INT8 | 150 MHz | 208.18 MHz | 1.890364 mm² | 1.2800 W | Physically closed |

All three validated physical references completed routing with zero reported setup and hold violations, zero route DRC violations, and zero reported antenna violations in the retained AccelClosure evidence.

## Fresh Autonomous Prompt-to-GDS Demonstration

An independent 8x8 WS INT8 request targeting Sky130 at 180 MHz was executed through the public AccelClosure autonomous flow. The run completed physical implementation with a post-route Fmax estimate of 208.95 MHz, +0.77 ns worst setup slack, 0.497935 mm² routed area, 0.317 W vectorless power, zero setup/hold violations, zero route DRC violations, and a final GDSII artifact.

## 32x32 Scalability Evidence

A fresh natural-language 32x32 WS INT8 request targeting 150 MHz successfully progressed through contract generation, RTL generation, functional verification, synthesis, and pre-layout STA. It met the requested timing target with +2.48 ns setup slack and an estimated pre-layout Fmax of 238.99 MHz.

Physical implementation was intentionally stopped during placement. No post-route or GDSII claim is made for the 32x32 configuration.

## Claim Boundary

The current physically validated backend is square weight-stationary INT8 on Sky130HD. Other dataflows, precisions, and shapes are represented as extensible design-space dimensions and must not be interpreted as already physically validated implementations.

PPA measurements are configuration-specific. AccelClosure does not reuse physical PPA measurements across new accelerator configurations.
