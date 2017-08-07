"""Parses configuration files"""

import collections
import json

from jsonschema import validate
from jsonschema.exceptions import ValidationError

SCHEMA = "config/schema.json"

def load_json(filepath):
    with open(filepath, 'r') as json_file:
        return json.loads(json_file.read())


class ConfParse(object):
    def __init__(self, conf_file, haproxy_conf_file):
        self._haproxy = {}
        self._haproxy['services'] = {}
        schema = load_json(SCHEMA)
        self._config = load_json(conf_file)
        try:
            validate(self._config, schema)
        except ValidationError as err:
            print(err.message)
        self._haproxy_file = haproxy_conf_file

    def parse_config(self):
        if 'haproxy' in self._config:
            # Loop to ensure that OrderedDict receives headers in correct order
            self._haproxy['conf'] = collections.OrderedDict()
            self._haproxy['conf']['global'] = []
            self._haproxy['conf']['defaults'] = []
            self._haproxy['conf']['listen stats'] = []
            socket = 'stats socket /run/haproxy/admin.sock mode 600 level admin'
            self._haproxy['conf']['global'].append(socket)
            self._haproxy['conf']['global'].append('stats timeout 2m')
            for header in self._config['haproxy']:
                self._haproxy['conf'][header] += self._config['haproxy'][header]

        services = {}


        for service, info in self._config['services'].items():
            services[service] = info

            if 'elasticity' in info:
                info['elasticity'].setdefault('min_servers', 0)
                info['elasticity'].setdefault('max_servers', None)

                if ('hold_conns' in info['elasticity'] and
                        info['elasticity']['hold_conns']):
                    self.add_listen_block(service + '_proxy',
                                          info['haproxy']['listen'],
                                          info['haproxy']['port'])
                    self.add_listen_block(service, info['haproxy']['listen'],
                                          info['haproxy']['port'] + 1)
                    info['elasticity']['shutoff_time'] = 0
                    info['elasticity']['min_servers'] = 0
                    continue

            self.add_listen_block(service, info['haproxy']['listen'],
                                  info['haproxy']['port'])

        return services

    def add_listen_block(self, service, properties, port):
        bind = 'bind *:{}'
        self._haproxy['services'][service] = {}
        self._haproxy['services'][service]['properties'] = properties.copy()
        (self._haproxy['services'][service]
         ['properties'].append(bind.format(port)))
        self._haproxy['services'][service]['servers'] = {}

    def remove_listen_block(self, service):
        del self._haproxy['services'][service]

    def add_server(self, service, instance, address, properties):
        # print(instance)
        # print(self._haproxy['services'][service]['servers'])
        self._haproxy['services'][service]['servers'][instance] = {}
        (self._haproxy['services'][service]['servers']
         [instance]['address']) = address
        properties = ' '.join(properties)
        (self._haproxy['services'][service]['servers']
         [instance]['properties']) = properties

    def delete_server(self, service, instance):
        del self._haproxy['services'][service]['servers'][instance]

    def server_exists(self, service, instance):
        return instance in self._haproxy['services'][service]['servers']

    def get_servers(self, service):
        return self._haproxy['services'][service]['servers'].copy()

    def config_write(self):
        with open(self._haproxy_file, 'w+') as haproxy_conf:
            if 'conf' in self._haproxy:
                for header, props in self._haproxy['conf'].items():
                    haproxy_conf.write(header + '\n')
                    for prop in props:
                        haproxy_conf.write('\t' + prop + '\n')
            for service, config in self._haproxy['services'].items():
                listen_block = 'listen {}'.format(service)
                haproxy_conf.write(listen_block + '\n')
                for prop in config['properties']:
                    haproxy_conf.write('\t' + prop + '\n')
                for server, info in config['servers'].items():
                    server_base = '\tserver {} {} {}\n'
                    haproxy_conf.write(server_base.format(server,
                                                          info['address'],
                                                          info['properties']))
