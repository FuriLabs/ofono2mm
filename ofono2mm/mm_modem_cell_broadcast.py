from dbus_fast.service import ServiceInterface, method, dbus_property, signal
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant

from ofono2mm.mm_cbm import MMCbmInterface
from ofono2mm.logging import ofono2mm_print

cbm_i = 0

class MMModemCellBroadcastInterface(ServiceInterface):
    def __init__(self, bus, modem_name, ofono_interfaces, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem.CellBroadcast')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Cell Broadcast interface", verbose)
        self.bus = bus
        self.ofono_interfaces = ofono_interfaces
        self.verbose = verbose
        self.props = {
            'CellBroadcasts': Variant('ao', []),
            'Channels': Variant('a(uu)', [[0, 0]])
        }

    async def init_cbs(self):
        ofono2mm_print("Initializing signals", self.verbose)

        if 'org.ofono.CellBroadcast' in self.ofono_interfaces:
            self.ofono_interfaces['org.ofono.CellBroadcast'].on_incoming_broadcast(self.add_incoming_broadcast)
            self.ofono_interfaces['org.ofono.CellBroadcast'].on_emergency_broadcast(self.add_emergency_broadcast)
            try:
                await self.ofono_interfaces['org.ofono.CellBroadcast'].call_set_property('Powered', Variant('b', True))
            except Exception as e:
                ofono2mm_print(f"Failed to set org.ofono.CellBroadcast Powered to True: {e}", self.verbose)
        else:
            ofono2mm_print("org.ofono.CellBroadcast was not available when initializing cell broadcast", self.verbose)

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
        else:
            ofono2mm_print(f"{path} is not a valid object path", self.verbose)

    @method()
    def SetChannels(self, channels: 'a(uu)'):
        ofono2mm_print(f"Setting channels to {channels}", self.verbose)
        old_channels = self.props['Channels'].value
        self.props['Channels'] = Variant('a(uu)', channels)

        if old_channels != channels:
            self.emit_properties_changed({'Channels': self.props['Channels'].value})

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
    def Channels(self) -> 'a(uu)':
        return self.props['Channels'].value
