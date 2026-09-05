"""The product command surface."""

import click

from .delivery_worldline import worldline
from .delivery_state import delivery_state
from .project_setup import setup
from .skill_check import doctor
from .ticket_graph import ticket
from .ticket_integration import integrate_command


@click.group()
def main():
    """Configure and diagnose a Harness Project."""


main.add_command(setup)
main.add_command(doctor)
main.add_command(worldline)
main.add_command(ticket)
ticket.add_command(integrate_command)
main.add_command(delivery_state)
