"""Parses configuration files"""

from collections import OrderedDict
import json

from jsonschema import validate
from jsonschema.exceptions import ValidationError

SCHEMA = "config/schema.json"

def load_json(filepath):
    """Loads JSON config from file path as an OrderedDict
    Needs to keep the config for haproxy in the correct order"""
    with open(filepath, 'r') as json_file:
        return json.loads(json_file.read(), object_pairs_hook=OrderedDict)


class ConfParse(object):
    """Parses user config file and writes to the haproxy config file"""
    def __init__(self, socket, conf_file, haproxy_conf_file):
        """Loads the schema and validates the user config against it"""
        self._haproxy = {}
        self._haproxy['services'] = {}
        self._socket = socket

        self._config = load_json(conf_file)

        try:
            validate(self._config, load_json(SCHEMA))
        except ValidationError as err:
            print(err.message)

        self._haproxy_file = haproxy_conf_file

    def parse_config(self):
        """Parses user config file"""
        if 'haproxy' in self._config:
            # Haproxy conf must be OrderedDict because the order matters
            # for haproxy config
            self._haproxy['conf'] = OrderedDict()
            for header in self._config['haproxy']:
                self._haproxy['conf'][header] = self._config['haproxy'][header]

            # Config settings to enable Unix socket
            self._haproxy['conf'].setdefault('global', [])
            socket = 'stats socket {}/admin.sock mode 600 level admin'
            self._haproxy['conf']['global'].append(socket.format(self._socket))
            self._haproxy['conf']['global'].append('stats timeout 2m')

        services = {}

        for service, info in self._config['services'].items():
            services[service] = info

            if 'elasticity' in info:
                # Need defaults to prevent errors in pool
                info['elasticity'].setdefault('min_servers', 0)
                info['elasticity'].setdefault('max_servers', None)

                if ('hold_conns' in info['elasticity'] and
                        info['elasticity']['hold_conns']):
                    self.add_proxy(service, info['haproxy']['listen'],
                                   info['haproxy']['port'])
                    # Shutoff time necessary for hold conns algorithm
                    # Min servers must be 0 for hold conns algorithm to work
                    info['elasticity']['shutoff_time'] = 0
                    info['elasticity']['min_servers'] = 0
                    continue

            self.add_listen_block(service, info['haproxy']['listen'],
                                  info['haproxy']['port'])

        return services

    def add_listen_block(self, service, properties, port):
        """Add a listen block to the config"""
        # Format for port on haproxy config
        bind = 'bind *:{}'
        self._haproxy['services'][service] = {}
        # Copy to avoid doubling up on properties when running add_proxy
        # Appending port to non copy means that subsequent calls to
        # add_listen_block with the same properties will double up on port
        self._haproxy['services'][service]['properties'] = properties.copy()
        (self._haproxy['services'][service]
         ['properties'].append(bind.format(port)))
        self._haproxy['services'][service]['servers'] = {}

    def add_proxy(self, service, properties, port):
        """Adds two listen blocks to the config. First will point to the actual
        server. The second points to the first listen block."""
        proxy_properties = properties
        # Timeout must be longer because the connection is kept waiting while
        # a treadmill instance is launched
        proxy_properties.append('timeout server 1d')

        # Give the proxy the actual port, because that is where users will
        # connect to.
        self.add_listen_block(service + '_proxy', proxy_properties, port)

        # Point the proxy block to the service block
        self.add_server(service + '_proxy', service, '0.0.0.0:' + str(port + 1),
                        ['check'])
        self.add_listen_block(service, properties, port + 1)

    def remove_listen_block(self, service):
        """Remove a listen block"""
        del self._haproxy['services'][service]

    def add_server(self, service, instance, address, properties):
        """Adds a server to a service"""
        self._haproxy['services'][service]['servers'][instance] = {}
        (self._haproxy['services'][service]['servers']
         [instance]['address']) = address
        properties = ' '.join(properties)
        (self._haproxy['services'][service]['servers']
         [instance]['properties']) = properties

    def delete_server(self, service, instance):
        """Deletes a server from a service"""
        del self._haproxy['services'][service]['servers'][instance]

    def server_exists(self, service, instance):
        """Checks if a server exists"""
        return instance in self._haproxy['services'][service]['servers']

    def get_servers(self, service):
        """Returns a copy of a service's servers"""
        return self._haproxy['services'][service]['servers'].copy()

    def config_write(self):
        """Actually write the config stored in a dictionary into the file"""
        with open(self._haproxy_file, 'w+') as haproxy_conf:
            # Write the haproxy configuration separately
            if 'conf' in self._haproxy:
                for header, props in self._haproxy['conf'].items():
                    haproxy_conf.write(header + '\n')
                    for prop in props:
                        haproxy_conf.write('\t' + prop + '\n')

            # Write the service configs
            for service, config in self._haproxy['services'].items():
                # Format for listen block name
                listen_block = 'listen {}'.format(service)
                haproxy_conf.write(listen_block + '\n')
                for prop in config['properties']:
                    haproxy_conf.write('\t' + prop + '\n')
                # Write each server under the appropriate listen block
                for server, info in config['servers'].items():
                    server_base = '\tserver {} {} {}\n'
                    haproxy_conf.write(server_base.format(server,
                                                          info['address'],
                                                          info['properties']))
