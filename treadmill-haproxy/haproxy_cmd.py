"""Controls the haproxy process"""

import logging
import psutil
import signal
import subprocess

PIDFILE = '/run/haproxy/haproxy.pid'
_LOGGER = logging.getLogger(__name__)

def haproxy_proc():
    """Reads the haproxy.pid file and creates a psutil Process"""
    with open(PIDFILE, 'r') as pid_file:
        try:
            proc = psutil.Process(int(pid_file.read().strip()))
        except (psutil.NoSuchProcess, FileNotFoundError):
            return None
        if proc.is_running():
            return proc
        return None

def start_haproxy():
    "Starts HAProxy"
    # Base command
    cmd = ['/usr/sbin/haproxy']
    # Config file
    cmd += ['-f', '/home/vagrant/treadmill-haproxy/config/haproxy.conf']
    # Store pid
    cmd += ['-p', PIDFILE]
    # daemon
    cmd += ['-D']
    subprocess.call(cmd)

def stop_haproxy():
    """Stops HAProxy if process actually exists"""
    proc = haproxy_proc()
    if proc:
        proc.send_signal(signal.SIGUSR1)
    else:
        _LOGGER.error('HAProxy is not running')

def restart_haproxy():
    """Restarts HAProxy if process actually exists"""
    proc = haproxy_proc()
    if proc:
        proc.send_signal(signal.SIGUSR1)
    else:
        _LOGGER.error('HAProxy is not running')
    # Base command
    cmd = ['/usr/sbin/haproxy']
    # Config file
    cmd += ['-f', '/home/vagrant/treadmill-haproxy/config/haproxy.conf']
    # Store pid
    cmd += ['-p', PIDFILE]
    # daemon
    cmd += ['-D']
    # Restart
    cmd += ['-sf', str(proc.pid)]
    subprocess.call(cmd)
