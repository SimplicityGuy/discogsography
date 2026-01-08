"""Load testing scenarios for different use cases.

This module provides predefined scenarios for common load testing patterns.
"""

# Smoke test - Minimal load to verify basic functionality
SMOKE_TEST = {
    "users": 1,
    "spawn_rate": 1,
    "run_time": "1m",
    "description": "Minimal load test to verify basic functionality",
}

# Light load - Normal daytime traffic
LIGHT_LOAD = {
    "users": 25,
    "spawn_rate": 5,
    "run_time": "5m",
    "description": "Simulate light daytime traffic (25 concurrent users)",
}

# Moderate load - Busy period
MODERATE_LOAD = {
    "users": 100,
    "spawn_rate": 10,
    "run_time": "10m",
    "description": "Simulate moderate traffic during busy periods (100 concurrent users)",
}

# Heavy load - Peak traffic
HEAVY_LOAD = {
    "users": 250,
    "spawn_rate": 25,
    "run_time": "15m",
    "description": "Simulate heavy peak traffic (250 concurrent users)",
}

# Stress test - Beyond normal capacity
STRESS_TEST = {
    "users": 500,
    "spawn_rate": 50,
    "run_time": "20m",
    "description": "Stress test to find breaking point (500 concurrent users)",
}

# Spike test - Sudden traffic increase
SPIKE_TEST = {
    "users": 200,
    "spawn_rate": 100,  # Very fast spawn rate
    "run_time": "5m",
    "description": "Simulate sudden traffic spike (200 users spawned quickly)",
}

# Endurance test - Long-running stability test
ENDURANCE_TEST = {
    "users": 100,
    "spawn_rate": 10,
    "run_time": "60m",
    "description": "Long-running test to check stability (1 hour)",
}

# Breakpoint test - Find maximum capacity
BREAKPOINT_TEST = {
    "users": 1000,
    "spawn_rate": 20,
    "run_time": "30m",
    "description": "Find system breaking point (up to 1000 users)",
}


def get_scenario_command(scenario_name: str, host: str = "http://localhost:8005") -> str:
    """Generate Locust command for a specific scenario.

    Args:
        scenario_name: Name of the scenario (e.g., 'MODERATE_LOAD')
        host: Target host URL

    Returns:
        Complete Locust command string
    """
    scenarios = {
        "SMOKE_TEST": SMOKE_TEST,
        "LIGHT_LOAD": LIGHT_LOAD,
        "MODERATE_LOAD": MODERATE_LOAD,
        "HEAVY_LOAD": HEAVY_LOAD,
        "STRESS_TEST": STRESS_TEST,
        "SPIKE_TEST": SPIKE_TEST,
        "ENDURANCE_TEST": ENDURANCE_TEST,
        "BREAKPOINT_TEST": BREAKPOINT_TEST,
    }

    if scenario_name not in scenarios:
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {list(scenarios.keys())}")

    scenario = scenarios[scenario_name]

    cmd = (
        f"locust -f tests/load/locustfile.py "
        f"--host={host} "
        f"--users {scenario['users']} "
        f"--spawn-rate {scenario['spawn_rate']} "
        f"--run-time {scenario['run_time']} "
        f"--headless "
        f"--csv tests/load/results/{scenario_name.lower()} "
        f"--html tests/load/results/{scenario_name.lower()}.html"
    )

    return cmd


def print_all_scenarios() -> None:
    """Print all available scenarios with descriptions."""
    scenarios = {
        "SMOKE_TEST": SMOKE_TEST,
        "LIGHT_LOAD": LIGHT_LOAD,
        "MODERATE_LOAD": MODERATE_LOAD,
        "HEAVY_LOAD": HEAVY_LOAD,
        "STRESS_TEST": STRESS_TEST,
        "SPIKE_TEST": SPIKE_TEST,
        "ENDURANCE_TEST": ENDURANCE_TEST,
        "BREAKPOINT_TEST": BREAKPOINT_TEST,
    }

    print("\n" + "=" * 80)
    print("AVAILABLE LOAD TEST SCENARIOS")
    print("=" * 80)

    for name, config in scenarios.items():
        print(f"\n📊 {name}")
        print(f"   Description: {config['description']}")
        print(f"   Users: {config['users']}")
        print(f"   Spawn Rate: {config['spawn_rate']} users/sec")
        print(f"   Duration: {config['run_time']}")
        print("\n   Command:")
        print(f"   {get_scenario_command(name)}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    print_all_scenarios()
