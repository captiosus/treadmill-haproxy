"""Temporary solution to starting and stopping treadmill containers"""

import subprocess

def start_app(app, manifest):
    cmd = ['treadmill', 'run', '--manifest', manifest, app]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    return proc.communicate()

def stop_container(app, instance):
    cmd = ['treadmill', 'stop', '--all', app + '#' + instance]
    subprocess.call(cmd)

def stop_app(app):
    cmd = ['treadmill', 'stop', '--all', app]
    subprocess.call(cmd)

def discover_app(app):
    cmd = ['treadmill', 'discovery', app]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    return proc.communicate()
