# RxnResid

![RxnResid model architecture](assets/rxnresid-architecture.svg)

RxnResid predicts activation barriers for candidate reaction paths that share
the same reactants. The model decomposes each prediction into a group-level
baseline and a path-specific residual:

```text
barrier(group, path) = baseline(group) + residual(group, path)
```

The editable architecture diagram is available in
[`assets/rxnresid-architecture.drawio`](assets/rxnresid-architecture.drawio).

## Model

The baseline branch represents the reactivity shared by every path in a
reactant group. A GINE encoder processes deduplicated reactant components, and
learned component identities parameterize a low-rank interaction surface. A
separate product encoder aggregates the complete candidate set and supplies a
group-level correction.

The residual branch distinguishes routes within the group. Independent
GINE-GATv2 encoders process the exact reaction-change graph and its
group-relative delta graph. Their representations are fused with product,
reactant-component, route-identity, and mapped reaction-center features. The
route scores are centered within each group before they are combined with the
baseline.

Both product aggregation and residual centering depend on group context. Each
training or inference batch must therefore contain every candidate path for a
reactant group.

## Setup

RxnResid supports Python 3.11 through 3.13 and uses `uv` for dependency
management:

```bash
git clone <repository-url>
cd RxnResid
make setup
```

CUDA users can install PyTorch Geometric extension wheels matched to the locked
PyTorch build with:

```bash
make pyg-accelerators
```

## Data

Input data is a path-wise CSV with one atom-mapped reaction candidate per row.
The default configuration expects:

| Column | Description |
| --- | --- |
| `rxn_smiles` | Atom-mapped reactants and candidate product |
| `G_T_activate` | Activation-barrier target |
| `ene_id`, `diene_id` | Reactant component identifiers |
| `prod_id` | Route identifier |

Paths are partitioned by reactant group to prevent a group from appearing in
more than one split. Dataset paths, column names, split metadata, and model
settings are defined in [`configs/rxnresid.yaml`](configs/rxnresid.yaml).

## Training

Train a fold from random initialization:

```bash
uv run python train.py \
  --config configs/rxnresid.yaml \
  --fold-index 0 \
  --output runs/fold-00
```

Run the group cross-validation scheduler:

```bash
uv run python scripts/run_cross_validation.py \
  --config configs/rxnresid.yaml \
  --output-root runs/cross-validation \
  --nproc-per-node 1 \
  --tasks-per-gpu 1 \
  --gpu-indices 0
```

Each fold directory contains the resolved configuration, split metadata,
training history, predictions, metrics, and checkpoint. Existing completed
folds are skipped when the scheduler is resumed.

## Inference

```bash
uv run python predict.py \
  --checkpoint runs/fold-00/checkpoint.pt \
  --data path/to/mapped_paths.csv \
  --output predictions.csv
```

The output reports the total prediction and its baseline and residual
components. Input rows must contain complete reactant groups.

## Repository

```text
assets/         model architecture source and rendering
configs/        model, data, and training configuration
data/           input data and group split manifest
scripts/        data preparation and training utilities
src/rxnresid/   model and training package
tests/          unit and integration tests
train.py        training entry point
predict.py      inference entry point
```

Generated runs and local caches are excluded from version control. Use
`make check` for formatting, linting, and static type checks, and `make test`
for the test suite.

## License

RxnResid is available under the terms of the [MIT License](LICENSE).
