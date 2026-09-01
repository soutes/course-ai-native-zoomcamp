"""Domain logic, deliberately free of Django imports where possible.

`github` talks to the network, `triage` decides, `render` shows. None of them import
Django models, which is what keeps them testable from plain fixtures - and what made
the move from a Typer CLI into a Django app cost one file.
"""
