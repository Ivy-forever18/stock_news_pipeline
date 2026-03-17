.PHONY: test test-p1 test-p1-verbose test-p2 test-p2-agent

test:
	pytest -q

test-p1:
	pytest -q tests/test_p1_tools_integration.py

test-p1-verbose:
	pytest -v tests/test_p1_tools_integration.py

test-p2:
	pytest -q tests/test_p2_api_end_to_end.py

test-p2-agent:
	pytest -q tests/test_p2_agent_orchestrator.py
