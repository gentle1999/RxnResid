from functools import lru_cache
from pathlib import Path

from rxnresid.data.change_graphs import reaction_change_graphs
from rxnresid.data.dataset import ReactionGroupDataset, ReactionGroupSample
from rxnresid.models.encoders import EncoderConfig
from rxnresid.models.heads import HeadConfig
from rxnresid.models.rxnresid import (
    MeanCenteredRouteConfig,
    MeanPairSurfaceConfig,
    RxnResidConfig,
    RxnResidModel,
)


DATA = Path("data/new_full_df_exact_balanced_40ene_40diene.csv")


@lru_cache(maxsize=1)
def dataset() -> ReactionGroupDataset:
    return ReactionGroupDataset(
        DATA,
        route_id_column="prod_id",
        cache_dir=".cache/rxnresid",
    )


def sample_of_size(size: int) -> ReactionGroupSample:
    source = next(sample for sample in dataset() if len(sample) >= size)
    mappings = source.mappings[:size]
    change_graphs = reaction_change_graphs(mappings)
    energies = source.energies[:size].clone()
    baseline_target = float(energies.mean().item())
    return ReactionGroupSample(
        group_id=f"{source.group_id}_size_{size}",
        substrate_group=source.substrate_group,
        path_cgrs=change_graphs.paths,
        path_delta_cgrs=change_graphs.deltas,
        reactant=source.reactant,
        components=source.components,
        component_keys=source.component_keys,
        products=source.products[:size],
        energies=energies,
        baseline_target=baseline_target,
        residual_targets=energies - baseline_target,
        route_ids=source.route_ids[:size].clone(),
        path_ids=tuple(f"{path_id}_size_{size}" for path_id in source.path_ids[:size]),
        mappings=mappings,
    )


def tiny_rxnresid_model(
    *,
    mapping_mode: str = "latent_diff",
    route_count: int = 8,
) -> RxnResidModel:
    encoder = EncoderConfig(type="gine", num_layers=1, dropout=0.0, pooling="sum")
    return RxnResidModel(
        RxnResidConfig(
            hidden_dim=16,
            pair=MeanPairSurfaceConfig(
                encoder=encoder,
                rank=4,
                identity_factors=True,
            ),
            route=MeanCenteredRouteConfig(
                path_encoder=encoder,
                product_encoder=encoder,
                route_count=route_count,
                route_embedding_dim=4,
                mapping_mode=mapping_mode,  # type: ignore[arg-type]
                mapping_hidden_dim=8,
                mapping_dropout=0.0,
                product_group_head=HeadConfig((8,)),
                route_head=HeadConfig((8,)),
            ),
        )
    )
