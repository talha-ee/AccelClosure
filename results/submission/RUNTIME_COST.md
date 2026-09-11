# AccelClosure Runtime and Cost Evidence

**Designed and developed by Talha Alam**

## Evidence Status

- Gemini/LLM dispatch is recorded in AccelClosure orchestrator logs.
- Existing artifacts do not record authoritative LLM input/output token counts.
- Existing artifacts do not record authoritative monetary API cost.
- Therefore no estimated or invented LLM dollar cost is reported.
- OpenROAD and synthesis logs contain measured EDA stage runtimes and memory usage.

## Observed N4 EDA Runtime Evidence

- Synthesis log contains measured elapsed-time and peak-memory records.
- Detailed routing runtime observed: 93.38 seconds.
- One physical-flow stage reports elapsed time: 2 minutes 19.66 seconds.
- Peak memory for that stage: approximately 1.77 GB.

These numbers are stage-level evidence and are not claimed as complete
end-to-end AccelClosure wall-clock runtime.

## Cost Reporting Policy

OpenROAD placement logs also use the word "cost" for optimization objectives
such as HPWL. Those values are not monetary costs.

AccelClosure reports monetary cost only when it is available from an
authoritative API, cloud-billing, or usage record.

LLM_TOKEN_USAGE_STATUS=NOT_RECORDED_IN_EXISTING_ARTIFACTS
LLM_MONETARY_COST_STATUS=NOT_RECORDED_IN_EXISTING_ARTIFACTS
EDA_RUNTIME_EVIDENCE_STATUS=AVAILABLE
