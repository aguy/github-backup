#!/usr/bin/env python
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

import os
import sys
import git
import json
import glob
import time
import shutil
import syslog
import logging
import tarfile
import optparse
import ConfigParser
from github3 import login
from tempfile import mkdtemp
from os.path import join, exists

TODAY=time.strftime("%Y-%m-%d")
REPO_URL = "https://%(username)s:%(password)s@github.com/%(organization)s/%(repository)s.git"
WIKI_URL = "https://%(username)s:%(password)s@github.com/%(organization)s/%(repository)s.wiki.git"

def remove_older_than(pattern, x):
    files = glob.glob(pattern)
    files.sort(key=lambda f: os.path.getmtime(f))
    for file in files[:-x]:
	os.remove(file)
        log("remove %s" % file)

def json_dump(fd, values):
    json.dump(values, fd, indent=4, sort_keys=True)

def dump_members(gh, org, destdir, retention, dirname='members'):

    ddir = join(destdir, dirname)
    archname = join(ddir, "%s-%s.tar.bz2" % ( dirname, TODAY ))

    if exists(archname):
        log("%s already exists" % archname)
        return

    if not os.path.isdir(ddir):
        os.mkdir(ddir)

    temp = mkdtemp(dir=destdir)
    for member in org.iter_members():
        fd = open(join(temp, "%s.json" % member.login), 'w')
        json_dump(fd, gh.user(member.login).to_json())
        fd.close()

    tar = tarfile.open(archname, "w:bz2")
    tar.add(temp, arcname=dirname)
    tar.close()
    shutil.rmtree(temp)
    log("%s are backed up in %s" % ( dirname, archname ))
    remove_older_than(join(ddir, "%s-*.tar.bz2" % dirname), retention)

def dump_teams(org, destdir, retention, dirname='teams'):

    ddir = join(destdir, dirname)
    archname = join(ddir, "%s-%s.tar.bz2" % ( dirname, TODAY))

    if exists(archname):
        log("%s already exists" % archname)
        return

    if not os.path.isdir(ddir):
        os.mkdir(ddir)

    temp = mkdtemp(dir=destdir)

    for team in org.iter_teams():
        fd = open(join(temp, "%s.json" % team.name), 'w')
        members = []
        for member in team.iter_members():
            members.append(member.to_json())

        json_dump(fd, members)
        fd.close()

    tar = tarfile.open(archname, "w:bz2")
    tar.add(temp, arcname=dirname)
    tar.close()
    shutil.rmtree(temp)
    log("%s are backed up in %s" % ( dirname, archname ))
    remove_older_than(join(ddir, "%s-*.tar.bz2" % dirname), retention)

def dump_repo_details(repo, destdir):
    fd = open(join(destdir, "%s.json" % repo.name), 'w')
    json_dump(fd, repo.to_json())
    fd.close()

def dump_collaborators(repo, destdir):
    fd = open(join(destdir, "%s-collaborators.json" % repo.name), 'w')
    members = []
    for team in repo.iter_teams():
        members.append(team.to_json())

    json_dump(fd, members)
    fd.close()

def dump_repo_issues(repo, destdir):
    fd = open(join(destdir, "%s-issues.json" % repo.name), 'w')
    fdc = open(join(destdir, "%s-issues-comments.json" % repo.name), 'w')
    issues  = []
    comments = []
    for issue in repo.iter_issues():
        issues.append(issue.to_json())
        for comment in issue.iter_comments():
            comments.append(comment.to_json())

    json_dump(fd, issues)
    json_dump(fdc, comments)
    fd.close()
    fdc.close()

def dump_repo_pulls(repo, destdir):
    fd = open(join(destdir, "%s-pulls.json" % repo.name), 'w')
    fdc = open(join(destdir, "%s-pulls-comments.json" % repo.name), 'w')
    pulls  = []
    comments = []
    for pull in repo.iter_pulls():
        pulls.append(pull.to_json())
        for comment in pull.iter_comments():
            comments.append(comment.to_json())

    json_dump(fd, pulls)
    json_dump(fdc, comments)
    fd.close()
    fdc.close()

def dump_repo(org, username, password, type, destdir, retention):

    count = 0

    for repo in org.iter_repos(type=type):
        try:
            repodir = "%s-repos" % type
            ddir = join(destdir, repodir)
            reponame = "%s-%s" % ( repo.name, repo.id )
            archname = join(ddir, "%s-%s.tar.bz2" % ( reponame, TODAY ))

            if exists(archname):
                log("%s already exists" % archname)
                continue

            if not os.path.isdir(ddir):
                os.mkdir(ddir)

            temp = mkdtemp(dir=destdir)

            repo_data = {
              'username' : username,
              'password' : password,
              'organization': org.login,
              'repository' : repo.name
            }

            git.Repo.clone_from(
                REPO_URL % repo_data, join(temp, repo.name), mirror=True)

            if repo.has_wiki:
                try:
                    git.Repo.clone_from(
                        WIKI_URL % repo_data, join(temp, "%s.wiki" % repo.name), mirror=True)
                except git.exc.GitCommandError:
                    pass # the wiki is enabled but empty!"

            dump_repo_details(repo, temp)
            dump_collaborators(repo, temp)
            dump_repo_pulls(repo, temp)

            if repo.has_issues:
                dump_repo_issues(repo, temp)

            tar = tarfile.open(archname, "w:bz2")
            tar.add(temp, arcname=reponame)
            tar.close()
            shutil.rmtree(temp)
            log("repo %s is backed up in %s" % ( repo.name, archname ))
            count += 1
            remove_older_than(join(ddir, "%s-*.tar.bz2" % reponame), retention)

        except:
            log("Unexpected error: %s" % sys.exc_info()[0])
            log("sleep 5 seconds and try again ...")
            shutil.rmtree(temp)
            time.sleep(5)

    return count

def log(msg):
    logging.warning(msg)

if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option("-c", "--config", dest="config", metavar="CONFIG",
        type="string", help="github-backup configuration file")

    (options, args) = parser.parse_args()
    if options.config is None:
        parser.error('configuration file not given')

    config = ConfigParser.ConfigParser()
    config.read(options.config)

    username = config.get('github-backup', 'username')
    password = config.get('github-backup', 'password')
    organization = config.get('github-backup', 'organization')
    destdir = config.get('github-backup', 'destdir')
    retention = int(config.get('github-backup', 'retention'))

    #syslog.openlog('github-backup')
    log("starting a new session of backup")

    gh = login(username, password)
    org = gh.organization(organization)

    dump_members(gh, org, destdir, retention)
    dump_teams(org, destdir, retention)

    public_count  = dump_repo(org, username, password, 'public', destdir, retention)
    private_count = dump_repo(org, username, password, 'private', destdir, retention)

    log("session is now completed, %s public and %s private repositories backed up" % ( public_count, private_count ))
    #syslog.closelog()
