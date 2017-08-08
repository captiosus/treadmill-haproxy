"""Watches Treadmill Discovery and adds servers to HAProxy"""

import logging

import treadmill_api

_LOGGER = logging.getLogger(__name__)


class Watcher(object):
    """Watches for treadmill instances and adds/removes corresponding servers
    in the haproxy config"""
    def __init__(self, service_name, service, haproxy_parser):
        self._service_name = service_name
        self._haproxy_parser = haproxy_parser

        self._treadmill = service['treadmill']
        self._haproxy_conf = service['haproxy']

    def discover_servers(self):
        """Parses through treadmill discovery to find valid endpoints"""
        servers = treadmill_api.discover_container(self._treadmill['appname'])
        valid = {}

        if servers:
            for instance, server in servers.items():
                # Checks for the endpoint specified in the config
                if self._treadmill['endpoint'] in server:
                    valid[instance] = server[self._treadmill['endpoint']]

        return valid

    def confirm_server(self, instance, address):
        """Confirms that a new treadmill instance is available and adds to
        haproxy config"""
        _LOGGER.info("Confirm pending server")
        self._haproxy_parser.add_server(
            self._service_name, instance, address,
            self._haproxy_conf['server'])

    def loop(self):
        """Main loop. checks all treadmill instances available and compares it
        to the servers stored in the haproxy config"""
        _LOGGER.info('Starting watcher loop for %s', self._service_name)
        up_servers = self.discover_servers()

        # If there are changes that need to be written to the config,
        # this is changed to True
        changes = False

        if up_servers:
            for instance, info in up_servers.items():
                # Add to config if not already present
                if not self._haproxy_parser.server_exists(self._service_name,
                                                          instance):
                    self.confirm_server(instance, info)
                    changes = True

        # Get all servers in the haproxy config
        all_servers = self._haproxy_parser.get_servers(self._service_name)
        for instance in all_servers.keys():
            # If no longer available, then delete
            if instance not in up_servers:
                self._haproxy_parser.delete_server(self._service_name, instance)
                changes = True

        # Return whether there are any changes that need to be committed
        return changes
