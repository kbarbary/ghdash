ghdash
======

Another simple github dashboard for teams. I don't know why.

Requires [requests](http://docs.python-requests.org/) and
[jinja2](jinja.pocoo.org/), and Python 2.7 or 3.3+.

## Usage

Add a file `users.txt` to this directory listing your team's github user names.

Fetch new events from github (saved to `data` directory).

```
ghdash.py fetch
```

Build a page with the events (written to a `output` directory).

```
ghdash.py build
```

## Authentication

GitHub limits the requests per hour allowed to their
API. Unauthenticated requests are allowed only 60 requests per
hour. To get 5000 requests per hour, add the line

```
machine api.github.com login GITHUB_USERNAME password GITHUB_PASSWORD
```

to your `~/.netrc` file. The requests library picks up these credentials
automatically.

You'll see the remaining requests per hour for each fetch:

```
$ ghdash.py fetch
 INFO: kbarbary: 1 new event          [4996/5000] 
```
