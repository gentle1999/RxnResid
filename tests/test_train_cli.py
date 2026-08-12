import pytest

from train import _build_parser, _validate_args


def test_selection_training_requires_fold_index() -> None:
    args = _build_parser().parse_args([])

    with pytest.raises(ValueError, match="--fold-index is required"):
        _validate_args(args)


def test_refit_requires_checkpoint_and_uses_checkpoint_fold() -> None:
    parser = _build_parser()

    with pytest.raises(ValueError, match="--checkpoint is required"):
        _validate_args(parser.parse_args(["--refit"]))

    _validate_args(parser.parse_args(["--refit", "--checkpoint", "selection.pt"]))

    with pytest.raises(ValueError, match="loaded from --checkpoint"):
        _validate_args(
            parser.parse_args(["--refit", "--checkpoint", "selection.pt", "--fold-index", "0"])
        )

    with pytest.raises(ValueError, match="--config is loaded"):
        _validate_args(
            parser.parse_args(["--refit", "--checkpoint", "selection.pt", "--config", "other.yaml"])
        )
    with pytest.raises(ValueError, match="--split-manifest is loaded"):
        _validate_args(
            parser.parse_args(
                [
                    "--refit",
                    "--checkpoint",
                    "selection.pt",
                    "--split-manifest",
                    "other.json",
                ]
            )
        )
    with pytest.raises(ValueError, match="cannot be combined"):
        _validate_args(
            parser.parse_args(
                [
                    "--refit",
                    "--checkpoint",
                    "selection.pt",
                    "--train-on-train-valid-from-scratch",
                ]
            )
        )


def test_two_stage_training_requires_fixed_stage_budgets() -> None:
    parser = _build_parser()

    with pytest.raises(ValueError, match="required for two-stage"):
        _validate_args(
            parser.parse_args(["--fold-index", "0", "--two-stage-train-valid-from-scratch"])
        )

    _validate_args(
        parser.parse_args(
            [
                "--fold-index",
                "0",
                "--two-stage-train-valid-from-scratch",
                "--stage1-epochs",
                "300",
                "--stage2-epochs",
                "180",
            ]
        )
    )


def test_selection_refit_from_scratch_requires_the_second_stage_budget() -> None:
    parser = _build_parser()

    with pytest.raises(ValueError, match="stage2-epochs is required"):
        _validate_args(parser.parse_args(["--fold-index", "0", "--selection-refit-from-scratch"]))

    _validate_args(
        parser.parse_args(
            [
                "--fold-index",
                "0",
                "--selection-refit-from-scratch",
                "--stage2-epochs",
                "180",
            ]
        )
    )

    with pytest.raises(ValueError, match="auxiliary-weight-factor"):
        _validate_args(
            parser.parse_args(
                [
                    "--fold-index",
                    "0",
                    "--selection-refit-from-scratch",
                    "--stage2-epochs",
                    "180",
                    "--stage2-auxiliary-weight-factor",
                    "-0.1",
                ]
            )
        )


def test_checkpoint_and_refit_only_options_are_restricted_to_refit() -> None:
    parser = _build_parser()

    with pytest.raises(ValueError, match="only valid with --refit"):
        _validate_args(parser.parse_args(["--fold-index", "0", "--checkpoint", "selection.pt"]))
    with pytest.raises(ValueError, match="--epoch-factor is only valid"):
        _validate_args(parser.parse_args(["--fold-index", "0", "--epoch-factor", "2"]))
    with pytest.raises(ValueError, match="--learning-rate-factor is only valid"):
        _validate_args(parser.parse_args(["--fold-index", "0", "--learning-rate-factor", "0.2"]))
