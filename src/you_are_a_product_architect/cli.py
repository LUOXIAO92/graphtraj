"""The product command surface."""

import click

from .project_setup import setup
from .skill_check import doctor


@click.group()
def main():
    """Configure and diagnose a Harness Project."""


main.add_command(setup)
main.add_command(doctor)
