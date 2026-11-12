# Contributing to xdfetch

Contributions are welcome, especially new outlets and bug fixes. Open an issue if you'd
like to talk something over first, or go straight to a pull request.

## Reporting a bug

Say which outlet and date (or which file) and what came out wrong. For a conversion bug,
the file as served helps most: `xdfetch get <id> --date <date> --format both` keeps it
beside the `.xd`.

## Adding an outlet

An outlet is a row of [`xdfetch/outlets.tsv`](xdfetch/outlets.tsv); the README's
[Outlets](README.md#outlets) section describes the columns and each adapter's `params`.

- If an existing adapter already speaks to the outlet's host (`url`, `page`, `amuse`, ...),
  a new row is all it takes. `xdfetch get <id> --registry your-rows.tsv` tries a row
  before it goes in the table.
- Otherwise the outlet needs an adapter in `xdfetch/adapters/`, and a converter in
  `xdfetch/convert/` if it serves a format xdfetch doesn't read yet.
- An outlet that needs a subscription reads the subscriber's own credential from an
  environment variable named in the row's `auth` column, as the `nytimes` rows do.
- In a row's `notes` and in docstrings, describe what the adapter does: what it asks for
  and what it saves.

## Tests and checks

    uv sync
    uv run pytest
    uv run ruff check && uv run ruff format --check
    uv run ty check

A change comes with tests. Network calls are mocked with `responses`, and puzzles in tests
are made up for the purpose (`tests/synthetic.py`). Please don't add real, published
puzzles to the repo.

## License

By contributing you agree that your work is released under the project's
[MIT license](LICENSE).
