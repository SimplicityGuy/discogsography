run.sh --cloud now:

1. Provisions infrastructure (waits)
1. Sets up hosts + deploys databases (waits)
1. Kicks off benchmarks in background on the controller (returns immediately)
1. Prints monitor/fetch/teardown commands and exits

After that, from your laptop:

- Monitor: ssh -i ~/.ssh/benchmark-key bench@<ip> 'tail -f /opt/benchmark/benchmark.log'
- Fetch results: cd investigations/infra && ansible-playbook playbooks/fetch-results.yml (safe to run anytime — shows status and grabs whatever's ready)
- Teardown: ansible-playbook playbooks/teardown.yml --vault-password-file=.vault-pass
