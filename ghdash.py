#!/usr/bin/env python
"""Fetch some events from github and put them on a page."""

from __future__ import print_function, division

import sys
import os
import json
import shutil
from datetime import datetime

import requests
from jinja2 import Template
from flask import Flask

app = Flask(__name__)

USERS_FILE = "users.txt"
TEMPLATE_DIR = "templates"  # HTML Jinja template
DATA_DIR = "data"  # used for cacheing
GH_USER_EVENTS_URL = "https://api.github.com/users/{}/events/public"


def info(msg):
    """Print a line in blue (assumes we have a color terminal!)"""
    print("\033[1m\033[34m", "INFO:", msg, "\033[0m")


def timeago(time):
    """Given an ISO-8601 formatted timestamp (UTC), return time ago as a
    timedelta object."""
    tnow = datetime.utcnow()
    t = datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")

    return tnow - t


def read_users(fname):
    """Read a file and split into lines, stripping comments starting with 
    a hash (#) and blank lines."""
    users = []
    with open(fname, "r") as f:
        for line in f.readlines():
            pos = line.find("#")
            if pos != -1:
                line = line[0:pos]
            line = line.strip(" \n")
            if len(line) > 0:
                users.append(line)

    return users


def write_poll_info(fname, etag, poll_interval):
    """Write polling metadata to file `fname`."""

    with open(fname, "w") as f:
        f.write(etag)
        f.write("\n")
        f.write(datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
        f.write("\n")
        f.write(str(poll_interval))


def read_poll_info(fname):
    """Return etag, poll_time (ISO 8601 formatted), poll_interval"""

    with open(fname, "r") as f:
        lines = [line.strip() for line in f]
        etag, poll_time, poll_interval = lines

    return etag, poll_time, int(poll_interval)


def fetch_user_events(user):
    """Fetch public github events for the given user."""

    dirname = os.path.join(DATA_DIR, "users", user)
    poll_fname = os.path.join(dirname, "poll-info")
    url = GH_USER_EVENTS_URL.format(user)

    # ensure user directory exists
    if not os.path.exists(dirname):
        os.makedirs(dirname)

    # Get a list of events already locally cached and special data we saved
    # about the last time we polled github.
    fnames = os.listdir(dirname)
    if "poll-info" in fnames:
        etag, poll_time, poll_interval = read_poll_info(poll_fname)
        fnames.remove("poll-info")
    else:
        etag, poll_time, poll_interval = None, None, None

    # Check if we already polled recently, respecting the poll interval.
    if poll_time is not None and poll_interval is not None:
        td = timeago(poll_time)
        t_sec = td.days * 86400 + td.seconds
        if t_sec < poll_interval:
            info("{}: polled {}s ago. Next poll allowed in {}s."
                 .format(user, t_sec, poll_interval - t_sec))
            return

    headers = {"If-None-Match": etag} if (etag is not None) else None
    r = requests.get(url, headers=headers)

    if r.status_code == 304:
        msg = user + ": up-to-date"

        # If we get this status code, it means that etag wasn't None
        # and that means that poll_interval was also not None.
        # update poll-info with the current time.
        write_poll_info(poll_fname, etag, poll_interval)

    elif r.status_code == 200:
        events = r.json()

        # write each new event to a separate file
        new = 0
        for event in events:
            id = event["id"]
            if id not in fnames:
                fname = os.path.join(dirname, id)
                with open(fname, "w") as f:
                    json.dump(event, f)
                new += 1
        msg = "{}: {} new event".format(user, new)
        if new > 1:
            msg += "s"

        # write the polling metadata
        write_poll_info(poll_fname, r.headers["etag"],
                        r.headers["x-poll-interval"])

    else:
        raise Exception("request to {} failed with status {}"
                        .format(url, r.status_code))

    # append rate limit info to message
    limit = r.headers['x-ratelimit-limit']
    remaining = r.headers['x-ratelimit-remaining']
    info("{:30s} [{:>4s}/{:>4s}]".format(msg, remaining, limit))

    
def read_user_events(user):
    """Read user events from json data already in the cache"""

    dirname = os.path.join(DATA_DIR, "users", user)
    fnames = os.listdir(dirname)
    if "poll-info" in fnames:
        fnames.remove("poll-info")

    events = []
    for fname in fnames:
        with open(os.path.join(dirname, fname)) as f:
            events.append(json.load(f))

    return events


def is_merge_event(event):
    if event["type"] == "PushEvent":
        if len(event["payload"]["commits"]) == 0:
            return False
        lastmsg = event["payload"]["commits"][-1]["message"]
        if lastmsg.lower().startswith("merge pull request"):
            return True

    return False


def filter_merges_in_user_events(events):
    return list(filter(lambda x: (not is_merge_event(x)), events))


def combine_push_events(events):
    """Aggregate a set of push events into a single AggPushEvent."""

    if len(events) == 1:
        return events[0]

    # get all commit messages
    commits = []
    for e in events:
        commits.extend(e["payload"]["commits"])

    # get total size
    distinct_size = sum([e["payload"]["distinct_size"] for e in events])

    # assumes that list is already sorted by time
    d = {"type": "AggPushEvent",
         "actor": events[0]["actor"],
         "repo": events[0]["repo"],
         "payload": {"commits": commits,
                     "distinct_size": distinct_size},
         "created_at": events[0]["created_at"],  # most recent
         "begin": events[0]["created_at"],  # most recent
         "end": events[-1]["created_at"]}  # least recent

    return d


def aggregate_pushes_in_user_events(events):
    """Aggregate nearby PushEvents in a single user's events.
    """

    # sort events by time
    events.sort(key=lambda x: x["created_at"], reverse=True)

    # split into repos
    names = set([e["repo"]["name"] for e in events])
    events_by_repo = {n: [] for n in names}
    for e in events:
        events_by_repo[e["repo"]["name"]].append(e)

    new_events = []
    for name in events_by_repo:
        aggevents = None
        t1 = None
        for event in events_by_repo[name]:
            if event["type"] != "PushEvent":
                new_events.append(event)
                continue

            if aggevents is None:
                aggevents = [event]
                t1 = datetime.strptime(event["created_at"],
                                       "%Y-%m-%dT%H:%M:%SZ")
            else:
                t2 = datetime.strptime(event["created_at"],
                                       "%Y-%m-%dT%H:%M:%SZ")
                dt = t1 - t2
                if dt.days < 1:
                    aggevents.append(event)
                else:
                    new_events.append(combine_push_events(aggevents))
                    aggevents = [event]
                    t1 = t2

        # clean up remaining events
        if aggevents is not None:
            new_events.append(combine_push_events(aggevents))

    return new_events


def fmt_timedelta(td):
    if td.days > 1:
        return "{} days ago".format(td.days)
    elif td.days == 1:
        return "1 day ago"
    elif td.seconds > 7200:
        return "{} hours ago".format(td.seconds // 3600)
    elif td.seconds > 3600:
        return "1 hour ago"
    elif td.seconds > 120:
        return "{} minutes ago".format(td.seconds // 60)
    elif td.seconds > 60:
        return "1 minute ago"
    else:
        return "just now"


def timeago(time):
    """Given an ISO-8601 formatted timestamp, return time ago as a timedelta
    object."""
    tnow = datetime.utcnow()
    t = datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")

    return tnow - t


def timeago_event(event):
    if event["type"] == "AggPushEvent":
        s1 = fmt_timedelta(timeago(event["begin"]))
        s2 = fmt_timedelta(timeago(event["end"]))
        if s1 == s2:
            return s1
        else:
            return '{} &ndash; {}'.format(s1, s2)
    else:
        return fmt_timedelta(timeago(event["created_at"]))

# -----------------------------------------------------------------------------
# Parsing events
#
# Different types of events have different payloads and thus will be parsed
# differently. The global PARSERS variable maps event types (e.g., "PushEvent")
# to parsing functions. Each parsing function should return either:
# (1) a dictionary with "icon" and "body" keys
# (2) `None` if the event is not of interest

def ghlink(s):
    """Return an HTML <a> tag with a link to github"""

    return '<a href="https://github.com/{s}">{s}</a>'.format(s=s)


def simplebody(event, action):
    return '{} {} {}'.format(ghlink(event["actor"]["login"]), action,
                             ghlink(event["repo"]["name"]))


def parse_watch(event):
    return {"icon": "star",
            "body": simplebody(event, "starred")}


def parse_fork(event):
    return {"icon": "repo-forked",
            "body": simplebody(event, "forked")}


def parse_public(event):
    return {"icon": "heart",
            "body": simplebody(event, "open-sourced")}


def parse_pullrequest(event):
    """Only return new and merged pull requests"""

    action = event["payload"]["action"]
    login = event["actor"]["login"]
    number = event["payload"]["number"]
    pr_url = event["payload"]["pull_request"]["html_url"]
    pr_title = event["payload"]["pull_request"]["title"]
    repo_name = event["repo"]["name"]

    # correct closed to merged.
    if action == "closed" and event["payload"]["pull_request"]["merged"]:
        action = "merged"

    if action == "opened" or action == "merged":
        body = ('{} {} pull request <a href="{}" title="{}">#{}</a> on {}'
                .format(ghlink(login), action, pr_url, pr_title, number,
                        ghlink(repo_name)))
        return {"icon": "git-pull-request",
                "body": body}
    else:
        return None


def parse_create(event):
    """Parse new repositories, new tags, but not branches"""

    ref_type = event["payload"]["ref_type"]
    login = event["actor"]["login"]
    repo_name = event["repo"]["name"]
    ref = event["payload"]["ref"]

    if ref_type == "repository":
        icon = "repo"
        body = "{} created {}".format(ghlink(login), ghlink(repo_name))
    elif ref_type == "tag":
        icon = "tag"
        body = "{} tagged {} on {}".format(ghlink(login), ref,
                                           ghlink(repo_name))
    else:
        return None

    return {"icon": icon, "body": body}


def parse_release(event):
    login = event["actor"]["login"]
    repo_name = event["repo"]["name"]
    tag_name = event["payload"]["release"]["tag_name"]

    body = "{} released {} of {}".format(ghlink(login), tag_name,
                                         ghlink(repo_name))

    return {"icon": "package", "body": body}


def parse_push(event):
    login = event["actor"]["login"]
    repo_name = event["repo"]["name"]
    commits = event["payload"]["commits"]
    ncommits = event["payload"]["distinct_size"]
    msg = "\n".join([c["message"].split("\n")[0] for c in commits])

    body = '{} pushed <a title="{}">{} commits</a> to {}'.format(
        ghlink(login), msg, ncommits, ghlink(repo_name))

    return {"icon": "git-commit", "body": body}


PARSERS = {"WatchEvent": parse_watch,  # stars a repo
           "PullRequestEvent": parse_pullrequest,  # anything to do with a PR
           "CreateEvent": parse_create,  # creates a repo, branch or tag
           "ForkEvent": parse_fork,  # fork a repo
           "PublicEvent": parse_public,  # open-source a repo
           "ReleaseEvent": parse_release,  # draft a release
           "PushEvent": parse_push,  # repo branch is pushed to
           "AggPushEvent": parse_push}  # custom "event" type we create


def parse(event):
    """Parse an event into a dictionary or None.
    
    If the event is one we are interested in, return a dictionary with
    "icon", "body", "time" and "timeago" keys.

    If the event is one we are not interested in, return None.
    """
    t = event["type"]
    if t not in PARSERS:
        return None
    d = PARSERS[t](event)
    if d is None:
        return None

    # append timestamp & time string
    d["time"] = event["created_at"]
    d["timeago"] = timeago_event(event)

    return d


# -----------------------------------------------------------------------------
# Main bits

def build_html(events):
    """Render contents of index.html page."""

    #sort events by time
    events.sort(key=lambda x: x["created_at"], reverse=True)

    # parse all events
    summaries = []
    for event in events:
        s = parse(event)
        if s is not None:
            summaries.append(s)

    # load template
    with open(os.path.join(TEMPLATE_DIR, "index.html")) as f:
        template_html = f.read()
    template = Template(template_html)

    return template.render(events=summaries)


@app.route("/")
def index():
    users = read_users(USERS_FILE)
    for user in users:
        fetch_user_events(user)

    allevents = []
    for user in users:
        events = read_user_events(user)
        events = filter_merges_in_user_events(events)
        events = aggregate_pushes_in_user_events(events)
        allevents.extend(events)

    return build_html(allevents)
