"""Parses configuration files"""

import collections
import json

from jsonschema import validate


SCHEMA = "../config/schema.json"

def load_json(filepath):
    with open(filepath, 'r') as f:
        return json.loads(f.read())


class ConfParse(object):
    def __init__(self, conf_file, haproxy_conf_file):
        self._haproxy_conf = collections.OrderedDict()
        schema = load_json(SCHEMA)
        self._config = load_json(conf_file)
        validate(self._config, schema)
        self._haproxy_conf_file = haproxy_conf_file

    def load_services(self):
        if 'haproxy' in self._config:
            # Loop to ensure that OrderedDict receives headers in correct order
            for header in self._config['haproxy']:
                self._haproxy_conf[header] = self._config['haproxy'][header]

            if 'services' not in self._config:
                return None

        services = {}
        req_fields = ['properties', 'port', 'treadmill', 'method']

        for service, info in self._config['services'].items():
            service_info = {}

            for field in req_fields:
                if field not in info:
                    print('err')
                    continue

            service_info['treadmill'] = info['treadmill']
            service_info['method'] = info['method']

            if 'min_servers' not in info:
                service_info['min_servers'] = 0

            if 'hold-conns' in info and info['hold-conns']:
                self.add_listen_block(service + '_proxy', info['properties'],
                                      info['port'])
                self.add_listen_block(service, info['properties'],
                                      info['port'] + 1)
                service_info['shutoff_time'] = 0
                service_info['min_servers'] = 0
            else:
                self.add_listen_block(service, info['properties'],
                                      info['port'])

            services[service] = service_info
        return services

    def add_listen_block(self, service, properties, port):
        self._haproxy_conf[service]['properties'] = properties
        bind = 'bind *:{}'
        self._haproxy_conf[service]['properties'].append(bind.format(port))
        self._haproxy_conf[service]['servers'] = {}

    def remove_listen_block(self, service):
        del self._haproxy_conf[service]

    def add_server(self, service, name, address, properties):
        self._haproxy_conf[service]['servers'][name] = {}
        self._haproxy_conf[service]['servers'][name]['address'] = address
        self._haproxy_conf[service]['servers'][name]['properties'] = properties

    def delete_server(self, service, name):
        del self._haproxy_conf[service]['servers'][name]

    def config_write(self):
        with open(self._haproxy_conf_file, 'w+') as f:
            for service, config in self._haproxy_conf.items:
                header = 'listen {}'.format(service)
                f.write(header + '\n')
                for prop in config['properties']:
                    f.write('\t' + prop + '\n')
                for server, info in config['servers'].items():
                    server_base = '\tserver {} {} {}\n'
                    f.write(server_base.format(server, info['address'],
                                               info['properties']))


if __name__ == '__main__':
    confparse = ConfParse('../config/treadmill-haproxy.json', '../config/haproxy.conf')
