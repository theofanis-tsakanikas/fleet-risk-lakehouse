# Real vehicle telemetry — VED sample

`ved_sample.csv` is a **real-world sample** from the Vehicle Energy Dataset (VED): 18 trips
by 10 vehicles recorded in Ann Arbor, Michigan (week of 2017-11-01), downsampled to one
reading per 2 seconds (~9,000 rows, original column layout preserved). It is the default
input of the replay pipeline (`src/replay/`), which streams these trips through the exact
same Bronze → Silver → Gold contract as the mock generators.

Selection criteria: valid GPS on ≥95% of readings, trip duration 8–25 minutes, top speed
≥60 km/h, and genuine hard-braking events (the biometric stream is conditioned on those —
see `src/replay/biometrics.py`).

## Source & attribution

- **Dataset:** G. S. Oh, D. J. Leblanc, H. Peng, *"Vehicle Energy Dataset (VED), A
  Large-scale Dataset for Vehicle Energy Consumption Research"* —
  [arXiv:1905.02081](https://arxiv.org/abs/1905.02081)
- **Repository:** <https://github.com/gsoh/VED>
- **License:** Apache License 2.0 (redistribution permitted with attribution)
- **Privacy:** locations in VED are de-identified at source by the dataset authors (random
  geo-fencing / fog). The replay layer additionally maps vehicle IDs onto the project's
  pseudonymised `DRV_xx` fleet, so no VED identifier reaches the lakehouse.

## Full dataset

To replay more than the committed sample, fetch the full dynamic data (~180 MB compressed)
into `data/ved/full/` (gitignored):

```bash
python scripts/fetch_ved.py
```
