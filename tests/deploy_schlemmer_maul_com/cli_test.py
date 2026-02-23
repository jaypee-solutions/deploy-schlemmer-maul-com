"""Test for cli."""

from typer.testing import CliRunner

from deploy_schlemmer_maul_com.cli import app

runner = CliRunner()


def test_cli() -> None:
    """Test for cli."""
    result = runner.invoke(app)
    assert result.exit_code == 2
    assert 'Usage' in result.output


def test_cli_run() -> None:
    """Test for run subcommand of the cli."""
    result = runner.invoke(app, 'run')
    assert result.exit_code == 0
    assert result.output == 'Hello, Deploy Schlemmer Maul!\n'
