ghdash
======

A very simple github newsfeed for teams.

Requires [requests](http://docs.python-requests.org/),
[jinja2](http://jinja.pocoo.org/),
[flask](http://flask.pocoo.org) and Python 2.7 or 3.3+.

## Usage

Add a file `users.txt` to this directory listing your team's github user names.

Launch the flask app in development mode:

```
$ export FLASK_APP=ghdash.py
$ flask run
 * Serving Flask app "ghdash"
 * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
```

The page will auto-refresh every 5 minutes, so it is suitable for
displaying on a monitor without intervention.


## Authentication

GitHub limits the requests per hour allowed to their
API. Unauthenticated requests are allowed only 60 requests per
hour, which you will quickly reach.
To get 5000 requests per hour, add the line

```
machine api.github.com login GITHUB_USERNAME password GITHUB_PASSWORD
```

to your `~/.netrc` file. The requests library picks up these credentials
automatically.

You'll see the remaining requests per hour for each fetch printed in the
terminal:

```
INFO: kbarbary: 1 new event          [4996/5000] 
```


## Rate limiting

The app respects GitHub's requested rate limits, so for frequent page
refreshes, you'll see something like:

```
INFO: kbarbary: polled 24s ago. Next poll allowed in 36s. 
```