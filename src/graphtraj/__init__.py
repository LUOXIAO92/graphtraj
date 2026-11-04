"""The GraphTraj distribution."""

# GraphTraj's own variables that no graftling child inherits: the hosted CLI
# channel and the GRAPHTRAJ_ prefix (the ``graftling.environment`` entry point).
# Kept here so graftling loads it without importing the rest of GraphTraj.
GRAFTLING_ENVIRONMENT = {'connections': ('GRAPHTRAJ_CLI_CONNECTION',), 'prefixes': ('GRAPHTRAJ_',)}
