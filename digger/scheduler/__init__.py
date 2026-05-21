"""Scheduled-run subsystem for the digger worker.

Runs user-configured scheduled recommendation reports on a cadence:
- ``runner.run_scheduled_for_user`` — generate one report for one user.
- ``runner.scheduler_loop`` — poll the API for due users and run them.
"""
