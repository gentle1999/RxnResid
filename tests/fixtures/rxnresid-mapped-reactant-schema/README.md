# RxnResid mapped-reactant schema compatibility fixture

This fixture contains three real two-path reaction groups extracted from the
active-learning exports.  In each file, the two rows have:

- the same unmapped reactant group;
- complete atom mapping on both sides;
- different exact `mapped_reactants` strings while the canonical unmapped
  reactant key is identical (the slash directions encode different mapped
  double-bond stereo assignments);
- path-specific products and activation free energies.

The current RxnResid implementation raises
`All paths in a group must use one consistent mapped reactant schema` for each
file.  This fixture is intended for the RxnResid-side compatibility change,
not for splitting the rows into separate groups.

## Input contract

Each CSV can be passed directly to `ReactionGroupDataset`:

```python
dataset = ReactionGroupDataset(
    "autode.csv",
    target_column="G_T_activate",
    reaction_column="rxn_smiles",
    route_id_column="prod_id",
)
```

The extra metadata columns are retained in `ReactionRow.metadata` and are not
needed by the parser.

## Compatibility target

For every fixture CSV, the corrected RxnResid implementation must satisfy:

```python
assert len(dataset.rows) == 2
assert len(dataset) == 1                 # do not split the substrate group
assert len(dataset[0].mappings) == 2     # retain both reaction paths
assert len(dataset[0].path_ids) == 2
assert len(dataset[0].energies) == 2
assert dataset.anomalies == []
```

The shared group graph may use a canonical/aligned representation, but the
implementation must retain enough information to represent each path's
reactant stereo, product mapping, target, path id, and route id.  It must not
silently discard one path or merge the two products into one reaction.  In
particular, treating the exact mapped reactant string as a hard equality check
is not an acceptable compatibility behavior for these groups.

`expected.json` records the source identifiers, target values, and the
expected structural counts for all three cases.  `autode.csv`,
`dpa-fined-rits-da.csv`, and `rits-zero-shot-da.csv` are deliberately kept
separate so labels from different projects are never mixed into one test
group.
