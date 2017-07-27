"""Main launcher for HAProxy watcher."""

import atexit
import logging

import click

from orchestrator import Orchestrator
import haproxy_control

_LOGGER = logging.getLogger(__name__)

@click.command()
@click.option('--socket', default='/run/haproxy/', help='HAProxy socket')
@click.option('--config', 'config_file',
              default='config/treadmill-haproxy.json',
              help="Configuration file")
@click.option('--haproxy-config', 'haproxy_file',
              default='config/haproxy.conf')
def main(socket, config_file, haproxy_file):
    """Configure logging and start monitering"""
    logging.basicConfig(level=logging.INFO)
    _LOGGER.setLevel(logging.INFO)
    orch = Orchestrator(socket, config_file, haproxy_file)
    orch.monitor()

def cleanup():
    haproxy_control.stop_haproxy()

if __name__ == '__main__':
    atexit.register(cleanup)
    main()
