"""Watches Treadmill Discovery and adds servers to HAProxy"""

import logging

import treadmill_api
import haproxy_control


class Watcher(object):
    def __init__(self, service_name, service, haproxy_parser):
        self._service_name = service_name
        self._haproxy_parser = haproxy_parser

        self._treadmill = service['treadmill']
        self._haproxy_conf = service['haproxy']

    def discover_servers(self):
        servers = treadmill_api.discover_container(self._treadmill['appname'])
        valid = {}

        if servers:
            for instance, server in servers.items():
                if server['name'] != 'ssh':
                    valid[instance] = server

        return valid

    def confirm_server(self, instance, address):
        logging.info("Confirm pending server")
        self._haproxy_parser.add_server(
            self._service_name, instance, address,
            self._haproxy_conf['server'])

    def commit_haproxy(self):
        self._haproxy_parser.config_write()
        haproxy_control.restart_haproxy()

    def loop(self):
        up_servers = self.discover_servers()

        if up_servers:
            for instance, info in up_servers.items():
                if not self._haproxy_parser.server_exists(self._service_name,
                                                          instance):
                    self.confirm_server(instance, info['address'])

        all_servers = self._haproxy_parser.get_servers(self._service_name)
        for instance in all_servers.keys():
            if instance not in up_servers:
                self._haproxy_parser.delete_server(self._service_name, instance)

        self.commit_haproxy()
