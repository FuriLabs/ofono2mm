import asyncio

from time import time
from uuid import uuid4

from dbus_fast.service import ServiceInterface, method
from dbus_fast import Variant

from ofono2mm.logging import ofono2mm_print

from dbus import SystemBus, Interface
from dbus.mainloop.glib import DBusGMainLoop

class MMModemSimpleInterface(ServiceInterface):
    def __init__(self, mm_modem, modem_name, ofono_interfaces, ofono_interface_props, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem.Simple')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Simple interface", verbose)
        self.mm_modem = mm_modem
        self.ofono_interfaces = ofono_interfaces
        self.ofono_interface_props = ofono_interface_props
        self.verbose = verbose
        self.props = {
             'state': Variant('u', 7), # on runtime enabled MM_MODEM_STATE_ENABLED
             'signal-quality': Variant('(ub)', [0, True]),
             'current-bands': Variant('au', []),
             'access-technologies': Variant('u', 0), # on runtime unknown MM_MODEM_ACCESS_TECHNOLOGY_UNKNOWN
             'm3gpp-registration-state': Variant('u', 0), # on runtime idle MM_MODEM_3GPP_REGISTRATION_STATE_IDLE
             'm3gpp-operator-code': Variant('s', ''),
             'm3gpp-operator-name': Variant('s', ''),
             'cdma-cdma1x-registration-state': Variant('u', 0),
             'cdma-evdo-registration-state': Variant('u', 0),
             'cdma-sid': Variant('u', 0),
             'cdma-nid': Variant('u', 0)
        }

    def update_simple_props(self):
        ofono2mm_print("Updating simple properties", self.verbose)

        if 'org.ofono.SimManager' in self.ofono_interface_props and 'Present' in self.ofono_interface_props['org.ofono.SimManager'].props:
            sim_props = self.ofono_interface_props['org.ofono.SimManager']
            if not sim_props['Present'].value:
                ofono2mm_print("SIM is not present. no need to set simple props", self.verbose)
                return
        else:
            ofono2mm_print("SIM manager is not up yet. cannot set simple props", self.verbose)
            return

        pin_required = sim_props['PinRequired'].value if 'PinRequired' in sim_props.props else None
        if pin_required is not None and pin_required != 'none':
            ofono2mm_print("SIM is still locked and/or not ready. cannot set simple props", self.verbose)
            return

        if 'org.ofono.NetworkRegistration' in self.ofono_interface_props:
            self.props['m3gpp-operator-name'] = Variant('s', self.ofono_interface_props['org.ofono.NetworkRegistration']['Name'].value if "Name" in self.ofono_interface_props['org.ofono.NetworkRegistration'].props else '')

            MCC = ''
            if 'MobileCountryCode' in self.ofono_interface_props['org.ofono.NetworkRegistration'].props:
                MCC = self.ofono_interface_props['org.ofono.NetworkRegistration']['MobileCountryCode'].value

            MNC = ''
            if 'MobileNetworkCode' in self.ofono_interface_props['org.ofono.NetworkRegistration'].props:
                MNC = self.ofono_interface_props['org.ofono.NetworkRegistration']['MobileNetworkCode'].value

            self.props['m3gpp-operator-code'] = Variant('s', f'{MCC}{MNC}')

            if 'Strength' in self.ofono_interface_props['org.ofono.NetworkRegistration'].props:
                strength = self.ofono_interface_props['org.ofono.NetworkRegistration']['Strength'].value
                if self.props['signal-quality'].value[0] != strength:
                    self.props['signal-quality'] = Variant('(ub)', [strength, True])

            if 'Status' in self.ofono_interface_props['org.ofono.NetworkRegistration'].props:
                if self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == 'registered' or self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == 'roaming':
                    self.props['state'] = Variant('u', 9) # registered MM_MODEM_STATE_REGISTERED
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == 'searching':
                    self.props['state'] = Variant('u', 8) # searching MM_MODEM_STATE_SEARCHING
                else:
                    self.props['state'] = Variant('u', 7) # enabled MM_MODEM_STATE_ENABLED

            if 'Status' in self.ofono_interface_props['org.ofono.NetworkRegistration'].props:
                if self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == "unregistered":
                    self.props['m3gpp-registration-state'] = Variant('u', 0) # idle MM_MODEM_3GPP_REGISTRATION_STATE_IDLE
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == "registered":
                    self.props['m3gpp-registration-state'] = Variant('u', 1) # home MM_MODEM_3GPP_REGISTRATION_STATE_HOME
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == "searching":
                    self.props['m3gpp-registration-state'] = Variant('u', 2) # searching MM_MODEM_3GPP_REGISTRATION_STATE_SEARCHING
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == "denied":
                    self.props['m3gpp-registration-state'] = Variant('u', 3) # denied MM_MODEM_3GPP_REGISTRATION_STATE_DENIED
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == "unknown":
                    self.props['m3gpp-registration-state'] = Variant('u', 4) # unknown MM_MODEM_3GPP_REGISTRATION_STATE_UNKNOWN
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == "roaming":
                    self.props['m3gpp-registration-state'] = Variant('u', 5) # roaming MM_MODEM_3GPP_REGISTRATION_STATE_ROAMING
            else:
                self.props['m3gpp-registration-state'] = Variant('u', 4) # unknown MM_MODEM_3GPP_REGISTRATION_STATE_UNKNOWN
        else:
            self.props['m3gpp-operator-name'] = Variant('s', '')
            self.props['m3gpp-operator-code'] = Variant('s', '')
            self.props['signal-quality'] = Variant('(ub)', [0, True])
            self.props['state'] = Variant('u', 7) # enabled MM_MODEM_STATE_ENABLED

        if 'org.ofono.NetworkRegistration' in self.ofono_interface_props and self.props['state'].value >= 7:
            if "Technology" in self.ofono_interface_props['org.ofono.NetworkRegistration'].props:
                current_tech = 0
                if self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "nr":
                    current_tech |= 1 << 15 # network is 5g MM_MODEM_ACCESS_TECHNOLOGY_5GNR
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "lte":
                    current_tech |= 1 << 14 # network is lte MM_MODEM_ACCESS_TECHNOLOGY_LTE
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "hspap":
                    current_tech |= 1 << 9 # network is hspa plus MM_MODEM_ACCESS_TECHNOLOGY_HSPA_PLUS
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "hspa":
                    current_tech |= 1 << 8 # network is hspa MM_MODEM_ACCESS_TECHNOLOGY_HSPA
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "hsupa":
                    current_tech |= 1 << 7 # network is hsupa MM_MODEM_ACCESS_TECHNOLOGY_HSUPA
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "hsdpa":
                    current_tech |= 1 << 6 # network is hsdpa MM_MODEM_ACCESS_TECHNOLOGY_HSDPA
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "umts":
                    current_tech |= 1 << 5 # network is umts MM_MODEM_ACCESS_TECHNOLOGY_UMTS
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "edge":
                    current_tech |= 1 << 4 # network is edge MM_MODEM_ACCESS_TECHNOLOGY_EDGE
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "gprs":
                    current_tech |= 1 << 3 # network is gprs MM_MODEM_ACCESS_TECHNOLOGY_GPRS
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "gsm":
                    current_tech |= 1 << 1 # network is gsm MM_MODEM_ACCESS_TECHNOLOGY_GSM

                self.props['access-technologies'] = Variant('u', current_tech)
            else:
                self.props['access-technologies'] = Variant('u', 0) # network is unknown MM_MODEM_ACCESS_TECHNOLOGY_UNKNOWN
        else:
            self.props['access-technologies'] = Variant('u', 0) # network is unknown MM_MODEM_ACCESS_TECHNOLOGY_UNKNOWN

        supported_bands = []
        gsm_bands = [1, 2, 3, 4, 14, 15, 16, 17, 18, 19, 20]
        umts_bands = [5, 6, 7, 8, 9, 10, 11, 12, 13, 210, 211, 212, 213, 214, 219, 220, 221, 222, 225, 226, 232]
        lte_bands = [31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 115]
        nr_bands = [301, 302, 303, 305, 307, 308, 312, 313, 314, 318, 320, 325, 326, 328, 329, 330, 334, 338, 339, 340, 341, 348, 350, 351, 353, 365, 366, 370, 371, 374, 375, 376, 377, 378, 379, 380, 381, 382, 383, 384, 386, 389, 390, 391, 392, 393, 394, 395, 557, 558, 560, 561]
        if 'org.ofono.RadioSettings' in self.ofono_interface_props:
            if 'AvailableTechnologies' in self.ofono_interface_props['org.ofono.RadioSettings'].props:
                ofono_techs = self.ofono_interface_props['org.ofono.RadioSettings']['AvailableTechnologies'].value
                if 'gsm' in ofono_techs:
                    supported_bands.extend(gsm_bands)
                if 'umts' in ofono_techs:
                    supported_bands.extend(umts_bands)
                if 'lte' in ofono_techs:
                    supported_bands.extend(lte_bands)
                if 'nr' in ofono_techs:
                    supported_bands.extend(nr_bands)

        self.props['current-bands'] = Variant('au', supported_bands)

    def fallback_bearer_path(self):
        # Bearer/0 always exists, but handing back one that never got an interface makes
        # NetworkManager fail the activation with "missing data port" and retry at once,
        # with no backoff. Only fall back to a bearer that is actually usable.
        path = '/org/freedesktop/ModemManager1/Bearer/0'
        fallback = self.mm_modem.bearers.get(path)
        if fallback is None or not fallback.props['Interface'].value:
            raise Exception("No connected bearer available to fall back to")

        return path

    @method()
    async def Connect(self, properties: 'a{sv}') -> 'o':
        ofono2mm_print(f"Connecting with properties {properties}", self.verbose)

        apn = properties['apn'].value if 'apn' in properties else ''
        if 'apn' not in properties:
            ofono2mm_print("User provided no apn, using default value ''", self.verbose)

        for b in list(self.mm_modem.bearers.keys()):
            if b not in self.mm_modem.bearers:
                # bearer was removed by a concurrent task while we were iterating
                continue
            bearer_apn = self.mm_modem.bearers[b].props['Properties'].value['apn'].value if 'apn' in self.mm_modem.bearers[b].props['Properties'].value else ''
            if bearer_apn == apn:
                self.mm_modem.bearers[b].props['Properties'] = Variant('a{sv}', properties)
                if self.mm_modem.bearers[b].active_connect == 0:
                    self.mm_modem.bearers[b].active_connect += 1
                    await self.mm_modem.bearers[b].doConnect()

                    ofono2mm_print(f"Bearer activated at path {b}", self.verbose)
                    return b
        try:
            bearer = await self.mm_modem.doCreateBearer(properties)
            if self.mm_modem.bearers[bearer].active_connect == 0:
                self.mm_modem.bearers[bearer].active_connect += 1
                await self.mm_modem.bearers[bearer].doConnect()
            else:
                ofono2mm_print(f"Failed to create bearer, active connect is {self.mm_modem.bearers[bearer].active_connect}", self.verbose)
                bearer = self.fallback_bearer_path()
        except Exception as e:
            ofono2mm_print(f"Failed to create bearer: {e}", self.verbose)
            bearer = self.fallback_bearer_path()

        ofono2mm_print(f"Bearer activated at path {bearer}", self.verbose)
        return bearer

    @method()
    async def Disconnect(self, path: 'o'):
        ofono2mm_print(f"Disconnecting object path {path}", self.verbose)

        if path == '/':
            for bearer_path in list(self.mm_modem.bearers):
                bearer = self.mm_modem.bearers.get(bearer_path)
                if bearer is None:
                    # bearer was removed while we were awaiting a previous disconnect
                    continue
                try:
                    await bearer.doDisconnect()
                except Exception as e:
                    ofono2mm_print(f"Failed to disconnect bearer {bearer_path}: {e}", self.verbose)
        elif path in self.mm_modem.bearers:
            try:
                await self.mm_modem.bearers[path].doDisconnect()
            except Exception as e:
                ofono2mm_print(f"Failed to disconnect bearer {path}: {e}", self.verbose)

    @method()
    def GetStatus(self) -> 'a{sv}':
        ofono2mm_print("Returning status", self.verbose)
        self.update_simple_props()
        return self.props

    async def network_manager_set_apn(self, force=False):
        ofono2mm_print("Generating Network Manager connection", self.verbose)

        if 'org.ofono.SimManager' in self.ofono_interface_props and 'Present' in self.ofono_interface_props['org.ofono.SimManager'].props:
            sim_props = self.ofono_interface_props['org.ofono.SimManager']
            if not sim_props['Present'].value:
                ofono2mm_print("SIM is not present. no need to set APN", self.verbose)
                return True
        else:
            ofono2mm_print("SIM manager is not up yet", self.verbose)
            await asyncio.sleep(3)
            return False

        pin_required = sim_props['PinRequired'].value if 'PinRequired' in sim_props.props else None
        if pin_required is not None and pin_required != 'none':
            ofono2mm_print("SIM is still locked and/or not ready", self.verbose)
            await asyncio.sleep(3)
            return False

        DBusGMainLoop(set_as_default=True)

        current_timestamp = int(time())

        try:
            sim_id = sim_props['CardIdentifier'].value
        except Exception as e:
            ofono2mm_print(f"Failed to get sim identifier: {e}", self.verbose)
            return False

        try:
            await self.mm_modem.add_ofono_interface('org.ofono.NetworkRegistration')
            if 'org.ofono.NetworkRegistration' not in self.ofono_interface_props or 'Name' not in self.ofono_interface_props['org.ofono.NetworkRegistration'].props:
                ofono2mm_print("Carrier name is not available yet", self.verbose)
                await asyncio.sleep(3)
                return False
            carrier_name = self.ofono_interface_props['org.ofono.NetworkRegistration']['Name'].value
            if not carrier_name:
                ofono2mm_print("Carrier name is empty. Not registered to a network yet", self.verbose)
                await asyncio.sleep(3)
                return False
        except Exception as e:
            ofono2mm_print(f"Failed to get carrier name: {e}", self.verbose)
            return False

        if 'org.ofono.ConnectionManager' not in self.ofono_interfaces:
            ofono2mm_print("Connection manager is not up yet", self.verbose)
            await asyncio.sleep(3)
            return False

        apn = ''
        username = ''
        password = ''
        try:
            contexts = await self.ofono_interfaces['org.ofono.ConnectionManager'].call_get_contexts()
            for ctx in contexts:
                ctx_type = ctx[1].get('Type', Variant('s', '')).value
                if ctx_type.lower() == "internet":
                    apn = ctx[1].get('AccessPointName', Variant('s', '')).value
                    username = ctx[1].get('Username', Variant('s', '')).value
                    password = ctx[1].get('Password', Variant('s', '')).value
        except Exception as e:
            ofono2mm_print(f"Failed to get contexts: {e}", self.verbose)
            return False

        connection_settings = {
            'connection': {
                'id': f'{carrier_name}',
                'uuid': str(uuid4()),
                'type': 'gsm',
                'timestamp': current_timestamp
            },
            'gsm': {
                'apn': f'{apn}',
                'sim-id': f'{sim_id}'
            },
            'ipv4': {
                'dns-priority': 120,
                'method': 'auto',
                'route-metric': 1050
            },
            'ipv6': {
                'method': 'auto'
            }
        }

        if username and password:
            connection_settings['gsm']['username'] = f'{username}'
            connection_settings['gsm']['password'] = f'{password}'

        try:
            self.network_manager_enable_wwan()
            conn = self.network_manager_connection_exists(f'{sim_id}')
            if not conn:
                conn = self.network_manager_add_connection(connection_settings)
                conn_settings = self.network_manager_get_connection_settings(conn)
                ofono2mm_print(f"Connection '{conn_settings['connection']['id']}' created successfully with timestamp {current_timestamp}.", self.verbose)

            if not force:
                active_connections = self.network_manager_get_active_connections()
                for active_conn in active_connections:
                    conn_path = self.network_manager_get_active_connection_connection(active_conn)
                    if conn_path == conn:
                        return True

            self.network_manager_activate_connection(conn)
            return True
        except Exception as e:
            ofono2mm_print(f"Failed to save network manager connection: {e}", self.verbose)
            return False

    def network_manager_add_connection(self, connection_settings):
        ofono2mm_print("Adding Network Manager connection", self.verbose)

        DBusGMainLoop(set_as_default=True)

        bus = SystemBus()
        nm = bus.get_object("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager/Settings")

        nm_settings = Interface(nm, "org.freedesktop.NetworkManager.Settings")
        return nm_settings.AddConnection(connection_settings)

    def network_manager_get_connection_settings(self, conn):
        DBusGMainLoop(set_as_default=True)

        bus = SystemBus()
        nm = bus.get_object("org.freedesktop.NetworkManager", conn)

        nm_connection = Interface(nm, "org.freedesktop.NetworkManager.Settings.Connection")
        return nm_connection.GetSettings()

    def network_manager_get_active_connections(self):
        DBusGMainLoop(set_as_default=True)

        bus = SystemBus()
        nm = bus.get_object("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager")

        props = Interface(nm, "org.freedesktop.DBus.Properties")
        return props.Get("org.freedesktop.NetworkManager", "ActiveConnections")

    def network_manager_get_active_connection_connection(self, active_conn):
        DBusGMainLoop(set_as_default=True)

        bus = SystemBus()
        nm = bus.get_object("org.freedesktop.NetworkManager", active_conn)

        props = Interface(nm, "org.freedesktop.DBus.Properties")
        return props.Get("org.freedesktop.NetworkManager.Connection.Active", "Connection")

    def network_manager_activate_connection(self, conn):
        ofono2mm_print(f"Activating Network Manager connection {conn}", self.verbose)

        DBusGMainLoop(set_as_default=True)

        bus = SystemBus()
        nm = bus.get_object("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager")

        nm_interface = Interface(nm, "org.freedesktop.NetworkManager")
        return nm_interface.ActivateConnection(conn, "/", "/")

    def network_manager_connection_exists(self, target_sim_id):
        ofono2mm_print(f"Checking if Network Manager connection exists for SIM ID {target_sim_id}", self.verbose)

        found = False

        DBusGMainLoop(set_as_default=True)

        bus = SystemBus()
        nm = bus.get_object("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager/Settings")

        nm_settings = Interface(nm, "org.freedesktop.NetworkManager.Settings")
        nm_settings.ReloadConnections()

        connections = nm_settings.ListConnections()

        for conn in connections:
            conn_settings = self.network_manager_get_connection_settings(conn)
            if 'gsm' in conn_settings and 'sim-id' in conn_settings['gsm']:
                apn = conn_settings['gsm']['sim-id']
                if apn == target_sim_id:
                    found = conn
                    break

        ofono2mm_print(f"Connection for SIM ID {target_sim_id} exists: {found}", self.verbose)
        return found

    def network_manager_enable_wwan(self):
        try:
            bus = SystemBus()
            nm_proxy = bus.get_object('org.freedesktop.NetworkManager', '/org/freedesktop/NetworkManager')

            props = Interface(nm_proxy, 'org.freedesktop.DBus.Properties')
            props.Set('org.freedesktop.NetworkManager', 'WwanEnabled', True)

            ofono2mm_print("WWAN radio enabled successfully", self.verbose)
        except Exception as e:
            ofono2mm_print(f"Failed to enable WWAN radio: {e}", self.verbose)
            return False
        return True
