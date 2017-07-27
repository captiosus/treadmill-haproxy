"""Temporary solution to starting and stopping treadmill containers"""

import subprocess

def start_container(app, manifest):
    cmd = ['treadmill', 'run', '--manifest', manifest, app]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    return proc.communicate()

def stop_container(app, instance):
    cmd = ['treadmill', 'stop', '--all', app + '#' + instance]
    subprocess.call(cmd)

def stop_containers(app):
    cmd = ['treadmill', 'stop', '--all', app]
    subprocess.call(cmd)

def discover_container(app, instance):
    cmd = ['treadmill', 'discovery', app + '#' + instance]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    return proc.communicate()
