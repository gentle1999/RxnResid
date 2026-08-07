from myrepositorytemplate import __version__
from myrepositorytemplate.main import main


def test_package_exposes_version() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_main_prints_greeting(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([]) == 0

    captured = capsys.readouterr()
    assert "Hello from myrepositorytemplate." in captured.out


def test_main_prints_version(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--version"]) == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == __version__
