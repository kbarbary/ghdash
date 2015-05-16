ghdash
======

Another simple github dashboard for teams. I don't know why.

## Requirements

- `requests`
- `jinja2`

## Usage

Add a file `users.txt` to this directory listing your team's github user names.

Fetch new events from github (saved to `data` directory).

```
ghdash fetch
```

Build a page with the events (written to a `output` directory).

```
ghdash build
```
