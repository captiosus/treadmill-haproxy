import psutil
import signal
import subprocess

PIDFILE = '/run/haproxy.pid'

def haproxy_proc():
    with open(PIDFILE, 'r') as f:
        return psutil.Process(int(f.read().strip()))

def start_haproxy():
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
    try:
        proc = haproxy_proc()
    except psutil.NoSuchProcess:
        return
    proc.terminate()

def restart_haproxy():
    try:
        proc = haproxy_proc()
    except psutil.NoSuchProcess:
        return
    proc.send_signal(signal.SIGUSR1)

def is_running():
    try:
        proc = haproxy_proc()
    except psutil.NoSuchProcess:
        return False
    return proc.is_running()
