"""Parses configuration files"""

import collections
import json

from jsonschema import validate
from jsonschema.exceptions import ValidationError

import haproxy_control

SCHEMA = "config/schema.json"

def load_json(filepath):
    with open(filepath, 'r') as f:
        return json.loads(f.read())


class ConfParse(object):
    def __init__(self, conf_file, haproxy_conf_file):
        self._haproxy = {}
        self._haproxy['services'] = {}
        schema = load_json(SCHEMA)
        self._config = load_json(conf_file)
        try:
            validate(self._config, schema)
        except ValidationError as e:
            print(e.message)
        self._haproxy_file = haproxy_conf_file

    def parse_config(self):
        if 'haproxy' in self._config:
            # Loop to ensure that OrderedDict receives headers in correct order
            self._haproxy['conf'] = {}
            socket = 'stats socket /run/haproxy/admin.sock mode 600 level admin'
            self._haproxy['conf']['global'] = []
            self._haproxy['conf']['defaults'] = []
            self._haproxy['conf']['global'].append(socket)
            self._haproxy['conf']['global'].append('stats timeout 2m')
            for header in self._config['haproxy']:
                self._haproxy['conf'][header] += self._config['haproxy'][header]

        services = {}


        for service, info in self._config['services'].items():
            info['elasticity'].setdefault('min_servers', 0)
            info['elasticity'].setdefault('max_servers', None)

            if 'hold-conns' in info and info['hold-conns']:
                self.add_listen_block(service + '_proxy',
                                      info['haproxy']['listen'],
                                      info['treadmill']['port'])
                self.add_listen_block(service, info['haproxy']['listen'],
                                      info['treadmill']['port'] + 1)
                info['elasticity']['shutoff_time'] = 0
                info['elasticity']['min_servers'] = 0
            else:
                self.add_listen_block(service, info['haproxy']['listen'],
                                      info['treadmill']['port'])

            services[service] = info
        return services

    def add_listen_block(self, service, properties, port):
        bind = 'bind *:{}'
        self._haproxy['services'][service] = {}
        self._haproxy['services'][service]['properties'] = properties
        self._haproxy['services'][service]['properties'].append(bind.format(port))
        self._haproxy['services'][service]['servers'] = {}

    def remove_listen_block(self, service):
        del self._haproxy['services'][service]

    def add_server(self, service, instance, address, properties):
        self._haproxy['services'][service]['servers'][instance] = {}
        self._haproxy['services'][service]['servers'][instance]['address'] = address
        self._haproxy['services'][service]['servers'][instance]['properties'] = properties

    def delete_server(self, service, instance):
        del self._haproxy['services'][service]['servers'][instance]

    def config_write(self):
        with open(self._haproxy_file, 'w+') as f:
            if 'conf' in self._haproxy:
                for header, props in self._haproxy['conf'].items():
                    f.write(header + '\n')
                    for prop in props:
                        f.write('\t' + prop + '\n')
            for service, config in self._haproxy['services'].items():
                listen_block = 'listen {}'.format(service)
                f.write(listen_block + '\n')
                for prop in config['properties']:
                    f.write('\t' + prop + '\n')
                for server, info in config['servers'].items():
                    server_base = '\tserver {} {} {}\n'
                    f.write(server_base.format(server, info['address'],
                                               info['properties']))
        if haproxy_control.is_running():
            haproxy_control.restart_haproxy()
        else:
            haproxy_control.start_haproxy()

if __name__ == '__main__':
    confparse = ConfParse('../config/treadmill-haproxy.json', '../config/haproxy.conf')
