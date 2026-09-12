"""The product command surface."""

import click

from graphtraj.interfaces.cli.worldline import worldline
from graphtraj.interfaces.cli.project_setup import setup, doctor
from graphtraj.interfaces.cli.ticket import delivery_state, ticket


@click.group()
def main() -> None:
    """Set up GraphTraj and manage Ticket, Team, and Project Worldline evidence.

    Configuration lives in .graphtraj; historical Delivery Runs have no
    compatibility reader or migration."""


main.add_command(setup)
main.add_command(doctor)
main.add_command(worldline)
main.add_command(ticket)
main.add_command(delivery_state)
