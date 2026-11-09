.PHONY: test test-system docker run version demo

test:
	PYTHONPATH=. python3 -m unittest discover -s tests -v

docker:
	docker build -t travelpayouts-mcp:local .

run:
	python3 -m travelpayouts_mcp

version:
	python3 -m travelpayouts_mcp --version

demo:
	@printf '%s\n' \
	  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
	  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
	  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
	  | PYTHONPATH=. python3 -m travelpayouts_mcp
