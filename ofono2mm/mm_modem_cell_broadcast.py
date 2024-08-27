import asyncio

from dbus_next.service import ServiceInterface, method, dbus_property, signal
from dbus_next.constants import PropertyAccess
from dbus_next import Variant

from ofono2mm.mm_cbm import MMCbmInterface
from ofono2mm.logging import ofono2mm_print

cbm_i = 0

class MMModemCellBroadcastInterface(ServiceInterface):
    def __init__(self, bus, ofono_client, modem_name, ofono_props, ofono_interfaces, ofono_interface_props, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem.CellBroadcast')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Cell Broadcast interface", verbose)
        self.bus = bus
        self.ofono_client = ofono_client
        self.ofono_props = ofono_props
        self.ofono_interfaces = ofono_interfaces
        self.ofono_interface_props = ofono_interface_props
        self.verbose = verbose
        self.props = {
            'CellBroadcasts': Variant('ao', []),
            'Enabled': Variant('b', True),
            'Channels': Variant('s', '')
        }

    def set_props(self):
        ofono2mm_print("Setting properties", self.verbose)

        old_props = self.props

        if 'org.ofono.CellBroadcast' in self.ofono_interfaces:
            self.props['Channels'] = Variant('s', self.ofono_interface_props['org.ofono.CellBroadcast']['Topics'].value)
            self.props['Enabled'] = Variant('b', self.ofono_interface_props['org.ofono.CellBroadcast']['Powered'].value)

        for prop in self.props:
            if self.props[prop].value != old_props[prop].value:
                self.emit_properties_changed({prop: self.props[prop].value})

    def init_cbs(self):
        ofono2mm_print("Initializing signals", self.verbose)

        if 'org.ofono.CellBroadcast' in self.ofono_interfaces:
            self.ofono_interfaces['org.ofono.CellBroadcast'].on_incoming_broadcast(self.add_incoming_broadcast)
            self.ofono_interfaces['org.ofono.CellBroadcast'].on_emergency_broadcast(self.add_emergency_broadcast)

    def add_incoming_broadcast(self, text, topic):
        ofono2mm_print(f"Add incoming broadcast text: {text}, topic: {topic}", self.verbose)
        global cbm_i
        mm_cbm_interface = MMCbmInterface(self.verbose)
        mm_cbm_interface.props.update({
            'State': Variant('u', 2), # hardcoded value received MM_CBM_STATE_RECEIVED
            'Text': Variant('s', text),
            'Channel': Variant('u', topic)
        })

        object_path = f'/org/freedesktop/ModemManager1/CBM/{cbm_i}'
        self.bus.export(object_path, mm_cbm_interface)
        self.props['CellBroadcasts'].value.append(object_path)
        self.emit_properties_changed({'CellBroadcasts': self.props['CellBroadcasts'].value})
        self.Added(object_path)
        cbm_i += 1

    def add_emergency_broadcast(self, text, props):
        ofono2mm_print(f"Add emergency broadcast text: {text} with properties {props}", self.verbose)
        ofono2mm_print(f"Add incoming broadcast text: {text}, topic: {topic}", self.verbose)
        global cbm_i
        mm_cbm_interface = MMCbmInterface(self.verbose)
        mm_cbm_interface.props.update({
            'State': Variant('u', 2), # hardcoded value received MM_CBM_STATE_RECEIVED
            'Text': Variant('s', text)
        })

        object_path = f'/org/freedesktop/ModemManager1/CBM/{cbm_i}'
        self.bus.export(object_path, mm_cbm_interface)
        self.props['CellBroadcasts'].value.append(object_path)
        self.emit_properties_changed({'CellBroadcasts': self.props['CellBroadcasts'].value})
        self.Added(object_path)
        cbm_i += 1

    @method()
    def List(self) -> 'ao':
        ofono2mm_print("Returning list of cell broadcasts", self.verbose)
        return self.props['CellBroadcasts'].value

    @method()
    def Delete(self, path: 'o'):
        ofono2mm_print(f"Deleting cell broadcast message with object path {path}", self.verbose)

        if path in self.props['CellBroadcasts'].value:
            self.props['CellBroadcasts'].value.remove(path)
            self.bus.unexport(path)
            self.emit_properties_changed({'CellBroadcasts': self.props['CellBroadcasts'].value})
            self.Deleted(path)

    @method()
    async def Enable(self, enable: 'b'):
        ofono2mm_print(f"Enable cell broacast: {enable}", self.verbose)
        self.props['Enabled'] = Variant('b', enable)
        await self.ofono_interfaces['org.ofono.CellBroadcast'].set_property('Powered', Variant('b', enable))

    @signal()
    def Added(self, path) -> 's':
        ofono2mm_print(f"Signal: Cell broadcast message added with object path {path}", self.verbose)
        return path

    @signal()
    def Deleted(self, path) -> 'o':
        ofono2mm_print(f"Signal: Cell broadcast message with deleted object path {path}", self.verbose)
        return path

    @dbus_property(access=PropertyAccess.READ)
    def CellBroadcasts(self) -> 'ao':
        return self.props['CellBroadcasts'].value

    @dbus_property(access=PropertyAccess.READ)
    def Enabled(self) -> 'b':
        return self.props['Enabled'].value

    @dbus_property(access=PropertyAccess.READ)
    def Channels(self) -> 's':
        return self.props['Channels'].value

    def ofono_changed(self, name, varval):
        self.ofono_props[name] = varval
        self.set_props()

    def ofono_client_changed(self, ofono_client):
        self.ofono_client = ofono_client

    def ofono_interface_changed(self, iface):
        def ch(name, varval):
            if iface in self.ofono_interface_props:
                self.ofono_interface_props[iface][name] = varval
            self.set_props()
        return ch
