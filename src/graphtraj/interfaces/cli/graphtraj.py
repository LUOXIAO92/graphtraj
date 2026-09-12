"""The product command surface."""

import click

from graphtraj.graph.delivery_worldline import worldline
from graphtraj.graph.delivery_state import delivery_state
from graphtraj.workspace.project_setup import setup
from graphtraj.configuration.skill_check import doctor
from graphtraj.graph.ticket_graph import ticket
from graphtraj.teams.coding.ticket_integration import integrate_command


@click.group()
def main():
    """Set up GraphTraj and manage Ticket, Team, and Project Worldline evidence.

    Configuration lives in .graphtraj; historical Delivery Runs have no
    compatibility reader or migration."""


main.add_command(setup)
main.add_command(doctor)
main.add_command(worldline)
main.add_command(ticket)
ticket.add_command(integrate_command)
main.add_command(delivery_state)
