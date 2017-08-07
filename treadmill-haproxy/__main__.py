"""Main launcher for HAProxy watcher."""

import logging

import click

from orchestrator import Orchestrator

_LOGGER = logging.getLogger(__name__)

@click.command()
@click.option('--socket', default='/run/haproxy/', help='HAProxy socket')
@click.option('--config', 'config_file',
              default='config/treadmill-haproxy.json',
              help="Configuration file")
@click.option('--haproxy-config', 'haproxy_file',
              default='config/haproxy.conf')
@click.option('--debug', is_flag=True, default=False)
def main(socket, config_file, haproxy_file, debug):
    """Configure logging and start monitering"""
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    orch = Orchestrator(socket, config_file, haproxy_file)
    orch.monitor()


if __name__ == '__main__':
    main()
