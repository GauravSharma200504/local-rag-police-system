# Evaluation results

This folder is filled by `python evaluation/scripts/run_evaluation.py` (or Reports → Experimental evaluation):

- `latest.json` / `run_<timestamp>.json` – full results including per-question rows and the exact environment
- `summary_<timestamp>.csv` – one row per configuration
- `per_question_<timestamp>.csv` – metrics per question and configuration
- `charts_<timestamp>_{retrieval,generation,latency}.png`

No results are shipped with the project: every number must come from a run on your hardware with your models.
