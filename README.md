# Jev_test1

Scratch project for the [`jev`](https://pypi.org/project/jev/) library — a decorator
that compiles Python function definitions into TypeSafe **Jev** (System One)
structured-decision queries. Jev generates no text; it answers typed questions
(yes/no probabilities, choices, scores) about a state in one parallel call.

## Setup

```sh
uv venv --python 3.14 .venv
uv pip install -p .venv jev pytest
```

## Test

```sh
.venv/bin/python -m pytest test_jev.py -v
```

`test_jev.py` exercises jev's offline seams — no `TYPESAFE_API_KEY` or network
needed (mock seam, state builder, compile-time field validation).

## Real calls

Set `TYPESAFE_API_KEY` in `.env` and make a decorated function body-less (`...`);
calling it then queries Jev. See [console.typesafe.ai](https://console.typesafe.ai).
