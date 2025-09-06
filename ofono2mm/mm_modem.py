import asyncio

from glob import glob
from time import time, sleep
from re import split
from ast import literal_eval
from copy import deepcopy

from dbus_fast.service import (ServiceInterface,
                               method, dbus_property, signal)
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant, DBusError, BusType

from ofono2mm.mm_modem_3gpp import MMModem3gppInterface
from ofono2mm.mm_modem_3gpp_ussd import MMModem3gppUssdInterface
from ofono2mm.mm_modem_3gpp_profile_manager import MMModem3gppProfileManagerInterface
from ofono2mm.mm_modem_messaging import MMModemMessagingInterface
from ofono2mm.mm_modem_simple import MMModemSimpleInterface
from ofono2mm.mm_modem_firmware import MMModemFirmwareInterface
from ofono2mm.mm_modem_cdma import MMModemCDMAInterface
from ofono2mm.mm_modem_time import MMModemTimeInterface
from ofono2mm.mm_modem_sar import MMModemSarInterface
from ofono2mm.mm_modem_oma import MMModemOmaInterface
from ofono2mm.mm_modem_signal import MMModemSignalInterface
from ofono2mm.mm_modem_location import MMModemLocationInterface
from ofono2mm.mm_sim import MMSimInterface
from ofono2mm.mm_bearer import MMBearerInterface
from ofono2mm.mm_modem_voice import MMModemVoiceInterface
from ofono2mm.mm_modem_cell_broadcast import MMModemCellBroadcastInterface
from ofono2mm.logging import ofono2mm_print
from ofono2mm.utils import read_setting, save_setting
from ofono2mm.ofono import Ofono, DBus
from ofono2mm.dbus_interface_properties import DBusInterfaceProperties
from ofono2mm.types import _BANDS

bearer_i = 0

class MMModemInterface(ServiceInterface):
    def __init__(self, loop, index, bus, ofono_client, modem_name, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Modem interface", verbose)
        self.loop = loop
        self.index = index
        self.bus = bus
        self.ofono_client = ofono_client
        self.ofono_proxy = self.ofono_client["ofono_modem"][modem_name]
        self.verbose = verbose
        self.ofono_modem = self.ofono_proxy['org.ofono.Modem']
        self.ofono_interfaces = {}
        self.ofono_interface_props = DBusInterfaceProperties(self.ofono_proxy, verbose)
        self.mm_cell_type = 0 # on runtime unknown MM_CELL_TYPE_UNKNOWN
        self.mm_sim_interface = None
        self.mm_modem3gpp_interface = None
        self.mm_modem3gpp_ussd_interface = None
        self.mm_modem3gpp_profile_manager_interface = None
        self.mm_modem_simple_interface = None
        self.mm_modem_firmware_interface = None
        self.mm_modem_time_interface = None
        self.mm_modem_cdma_interface = None
        self.mm_modem_sar_interface = None
        self.mm_modem_oma_interface = None
        self.mm_modem_signal_interface = None
        self.mm_modem_location_interface = None
        self.mm_modem_voice_interface = None
        self.mm_modem_messaging_interface = None
        self.mm_modem_cell_broadcast_interface = None
        self.mm_interface_objects = [f'/org/freedesktop/ModemManager1/Modem/{self.index}']
        self.mm_bearer_interfaces = []
        self.selected_current_mode = []
        self.sim = Variant('o', f'/org/freedesktop/ModemManager/SIM/{self.index}')
        self.bearers = {}

        self.was_powered = False
        self.enabled = True
        self.locked = False

        self.used_interfaces = {
            "org.ofono.Modem",
            "org.ofono.NetworkRegistration",
            "org.ofono.RadioSettings",
            "org.ofono.SimManager",
            "org.ofono.NetworkTime",
            "org.ofono.NetworkMonitor",
            "org.ofono.ConnectionManager",
            "org.ofono.MessageManager",
            "org.ofono.VoiceCallManager",
            "org.ofono.SupplementaryServices",
            "org.ofono.FuriLabs.AT",
            "org.ofono.CellBroadcast",
            "org.ofono.CallSettings",
        }

        self.interfaces_without_props = {
            "org.ofono.NetworkTime",
            "org.ofono.NetworkMonitor",
            "org.ofono.FuriLabs.AT",
            "org.ofono.CallSettings",
        }

        self.props = {
            'Sim': Variant('o', '/'),
            'SimSlots': Variant('ao', [f'/org/freedesktop/ModemManager/SIM/{self.index}']),
            'PrimarySimSlot': Variant('u', 0),
            'Bearers': Variant('ao', []),
            'SupportedCapabilities': Variant('au', [0]), # on runtime none MM_MODEM_CAPABILITY_NONE
            'CurrentCapabilities': Variant('u', 0), # on runtime none MM_MODEM_CAPABILITY_NONE
            'MaxBearers': Variant('u', 4),
            'MaxActiveBearers': Variant('u', 2),
            'MaxActiveMultiplexedBearers': Variant('u', 2),
            'Manufacturer': Variant('s', 'ofono'),
            'Model': Variant('s', ''),
            'Revision': Variant('s', '10000'),
            'CarrierConfiguration': Variant('s', ''),
            'CarrierConfigurationRevision': Variant('s', '0'),
            'HardwareRevision': Variant('s', '1000'),
            'DeviceIdentifier': Variant('s', self.modem_name),
            'Device': Variant('s', self.modem_name),
            'Physdev': Variant('s', '/dev/binder'),
            'Drivers': Variant('as', ['binder']),
            'Plugin': Variant('s', 'ofono2mm'),
            'PrimaryPort': Variant('s', self.modem_name),
            'Ports': Variant('a(su)', [[self.modem_name, 0]]), # on runtime unknown MM_MODEM_PORT_TYPE_UNKNOWN
            'EquipmentIdentifier': Variant('s', ''),
            'UnlockRequired': Variant('u', 0), # on runtime unknown MM_MODEM_LOCK_UNKNOWN
            'UnlockRetries': Variant('a{uu}', {}),
            'State': Variant('i', 6), # on runtime enabled MM_MODEM_STATE_ENABLED
            'StateFailedReason': Variant('u', 0), # on runtime unknown MM_MODEM_STATE_CHANGE_REASON_UNKNOWN
            'AccessTechnologies': Variant('u', 0), # on runtime unknown MM_MODEM_ACCESS_TECHNOLOGY_UNKNOWN
            'SignalQuality': Variant('(ub)', [0, False]),
            'OwnNumbers': Variant('as', []),
            'PowerState': Variant('u', 3), # on runtime power on MM_MODEM_POWER_STATE_ON
            'SupportedModes': Variant('a(uu)', [[0, 0]]), # on runtime allowed mode none, preferred mode none MM_MODEM_MODE_NONE
            'CurrentModes': Variant('(uu)', [0, 0]), # on runtime allowed mode none, preferred mode none MM_MODEM_MODE_NONE
            'SupportedBands': Variant('au', []),
            'CurrentBands': Variant('au', []),
            'SupportedIpFamilies': Variant('u', 7) # hardcoded value ipv4, ipv6 and ipv4v6 MM_BEARER_IP_FAMILY_IPV4 | MM_BEARER_IP_FAMILY_IPV6 | MM_BEARER_IP_FAMILY_IPV4V6
        }

        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{index}', self)

        self.loop.create_task(self.init_ofono_interfaces())
        self.ofono_modem.on_property_changed(self.ofono_changed)

    async def init_ofono_interfaces(self):
        ofono2mm_print("Initialize oFono interfaces", self.verbose)

        promises = []
        for iface in self.used_interfaces:
            promises.append(self.add_ofono_interface(iface))

        await asyncio.gather(*promises)

        await self.set_props()
        self.loop.create_task(self.init_connection_manager())

        await self.release_request_modemmanager()

    async def add_ofono_interface(self, iface):
        if iface not in self.used_interfaces:
            ofono2mm_print(f"Interface is {iface} which is unused, skipping", self.verbose)
            return

        retries_left = 5
        while retries_left > 0:
            try:
                ofono2mm_print(f"Add oFono interface for iface {iface} (attempts left: {retries_left})", self.verbose)
                await self.ofono_interface_props[iface].init(iface in self.interfaces_without_props)
                self.ofono_interfaces.update({iface: self.ofono_proxy[iface]})
                break
            except Exception as e:
                retries_left -= 1
                if retries_left > 0:
                    ofono2mm_print(f"oFono interface {iface} was not ready: {e}, retrying in 0.5s", self.verbose)
                    await asyncio.sleep(0.5)
                else:
                    ofono2mm_print(f"oFono interface {iface} failed after all retries: {e}", self.verbose)
                    return

        if self.mm_modem3gpp_interface:
            self.mm_modem3gpp_interface.ofono_interface_props = self.ofono_interface_props
        if self.mm_sim_interface:
            self.mm_sim_interface.ofono_interface_props = self.ofono_interface_props
        if self.mm_modem_voice_interface:
            self.mm_modem_voice_interface.ofono_interface_props = self.ofono_interface_props
        if self.mm_modem_simple_interface:
            self.mm_modem_simple_interface.ofono_interface_props = self.ofono_interface_props
        if self.mm_modem_signal_interface:
            self.mm_modem_signal_interface.ofono_interface_props = self.ofono_interface_props

        if iface not in self.interfaces_without_props:
            self.ofono_interface_props[iface].on('*', self.ofono_interface_changed(iface))

        if self.mm_modem3gpp_interface:
            await self.mm_modem3gpp_interface.set_props()
        if self.mm_sim_interface:
            self.mm_sim_interface.set_props()
        if self.mm_modem_signal_interface and iface == "org.ofono.NetworkMonitor":
            await self.mm_modem_signal_interface.set_props()

        if iface == "org.ofono.FuriLabs.AT":
            self.loop.create_task(self._restore_saved_bands())

    async def _restore_saved_bands(self):
        bands = read_setting("current_bands")
        if not bands or not bands.strip():
            return

        retries_left = 5
        while retries_left > 0:
            try:
                ofono2mm_print(f"Restoring saved bands: {bands} (attempts left: {retries_left})", self.verbose)
                await self._send_at_command(bands)
                # Also restore ERAT to 22
                await self._send_at_command("AT+ERAT=22")
                break
            except Exception as e:
                ofono2mm_print(f"Failed to restore saved bands: {e}", self.verbose)
                retries_left -= 1
                await asyncio.sleep(0.5)

        ofono2mm_print("Successfully restored saved bands", self.verbose)

    async def remove_ofono_interface(self, iface):
        ofono2mm_print(f"Remove oFono interface for iface {iface}", self.verbose)

        if iface in self.ofono_interfaces:
            self.ofono_interfaces.pop(iface)

        await self.set_props()

        if self.mm_modem3gpp_interface:
            await self.mm_modem3gpp_interface.set_props()
        if self.mm_sim_interface:
            self.mm_sim_interface.set_props()
        if self.mm_modem_signal_interface:
            await self.mm_modem_signal_interface.set_props()

    async def init_connection_manager(self):
        while True:
            ofono2mm_print("Waiting for oFono connection manager to appear", self.verbose)
            if 'org.ofono.ConnectionManager' in self.ofono_interfaces:
                ofono2mm_print("oFono connection manager appeared, initializing check ofono contexts", self.verbose)
                await self.check_ofono_contexts()
                await self.set_props()
                return
            await asyncio.sleep(0.3)

    async def init_network_time(self):
        while True:
            ofono2mm_print("Waiting for oFono network time to appear", self.verbose)
            if 'org.ofono.NetworkTime' in self.ofono_interfaces:
                ofono2mm_print("oFono network time appeared, initializing modem time interface", self.verbose)
                await self.mm_modem_time_interface.init_time()
                await self.set_props()
                return
            await asyncio.sleep(0.3)

    async def init_message_manager(self):
        while True:
            ofono2mm_print("Waiting for oFono message manager to appear", self.verbose)
            if 'org.ofono.MessageManager' in self.ofono_interfaces:
                ofono2mm_print("oFono message manager appeared, initializing modem messaging interface", self.verbose)
                self.mm_modem_messaging_interface.init_messages()
                await self.set_props()
                return
            await asyncio.sleep(0.3)

    async def init_voice_call_manager(self):
        while True:
            ofono2mm_print("Waiting for oFono voice call manager to appear", self.verbose)
            if 'org.ofono.VoiceCallManager' in self.ofono_interfaces:
                ofono2mm_print("oFono voice call manager appeared, initializing modem voice interface", self.verbose)
                self.mm_modem_voice_interface.init_calls()
                await self.set_props()
                return
            await asyncio.sleep(0.3)

    async def init_supplementary_services(self):
        while True:
            ofono2mm_print("Waiting for oFono supplementary services to appear", self.verbose)
            if 'org.ofono.SupplementaryServices' in self.ofono_interfaces:
                ofono2mm_print("oFono supplementary services appeared, initializing modem ussd interface", self.verbose)
                self.mm_modem3gpp_ussd_interface.init_ussd()
                await self.set_props()
                return
            await asyncio.sleep(0.3)

    async def init_cell_broadcast(self):
        while True:
            ofono2mm_print("Waiting for oFono cell broadcast to appear", self.verbose)
            if 'org.ofono.CellBroadcast' in self.ofono_interfaces:
                ofono2mm_print("oFono cell broadcast appeared, initializing cell broadcast interface", self.verbose)
                await self.mm_modem_cell_broadcast_interface.init_cbs()
                return
            await asyncio.sleep(0.3)

    async def init_mm_sim_interface(self):
        ofono2mm_print("Initialize SIM interface", self.verbose)

        self.mm_sim_interface = MMSimInterface(self.modem_name, self.ofono_interfaces, self.ofono_interface_props, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager/SIM/{self.index}', self.mm_sim_interface)
        self.mm_sim_interface.set_props()

        self.mm_interface_objects.append(f'/org/freedesktop/ModemManager/SIM/{self.index}')

        # When Present changes, call set_props on myself AND on the SIM interface
        async def _on_present_changed(prop, value):
            await self.set_props()
            self.mm_sim_interface.set_props()

        self.ofono_interface_props['org.ofono.SimManager'].on('Present', _on_present_changed)

    async def init_mm_3gpp_interface(self):
        ofono2mm_print("Initialize 3GPP interface", self.verbose)

        self.mm_modem3gpp_interface = MMModem3gppInterface(self.ofono_client, self.modem_name, self.ofono_interfaces, self.ofono_interface_props, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem3gpp_interface)
        await self.mm_modem3gpp_interface.set_props()

    async def init_mm_3gpp_ussd_interface(self):
        ofono2mm_print("Initialize 3GPP USSD interface", self.verbose)

        self.mm_modem3gpp_ussd_interface = MMModem3gppUssdInterface(self.modem_name, self.ofono_interfaces, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem3gpp_ussd_interface)

        self.loop.create_task(self.init_supplementary_services())

    async def init_mm_3gpp_profile_manager_interface(self):
        ofono2mm_print("Initialize 3GPP profile manager interface", self.verbose)

        self.mm_modem3gpp_profile_manager_interface = MMModem3gppProfileManagerInterface(self.ofono_client, self.modem_name, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem3gpp_profile_manager_interface)

    async def init_mm_simple_interface(self):
        ofono2mm_print("Initialize Simple interface", self.verbose)

        self.mm_modem_simple_interface = MMModemSimpleInterface(self, self.modem_name, self.ofono_interfaces, self.ofono_interface_props, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_simple_interface)

    async def init_mm_firmware_interface(self):
        ofono2mm_print("Initialize Firmware interface", self.verbose)

        self.mm_modem_firmware_interface = MMModemFirmwareInterface(self, self.modem_name, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_firmware_interface)
        self.mm_modem_firmware_interface.set_props()

    async def init_mm_time_interface(self):
        ofono2mm_print("Initialize Time interface", self.verbose)

        self.mm_modem_time_interface = MMModemTimeInterface(self.ofono_client, self.modem_name, self.ofono_interfaces, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_time_interface)

        self.loop.create_task(self.init_network_time())

    async def init_mm_cdma_interface(self):
        ofono2mm_print("Initialize CDMA interface", self.verbose)

        self.mm_modem_cdma_interface = MMModemCDMAInterface(self.modem_name, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_cdma_interface)

    async def init_mm_sar_interface(self):
        ofono2mm_print("Initialize SAR interface", self.verbose)

        self.mm_modem_sar_interface = MMModemSarInterface(self.modem_name, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_sar_interface)

    async def init_mm_oma_interface(self):
        ofono2mm_print("Initialize OMA interface", self.verbose)

        self.mm_modem_oma_interface = MMModemOmaInterface(self.modem_name, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_oma_interface)

    async def init_mm_signal_interface(self):
        ofono2mm_print("Initialize Signal interface", self.verbose)

        self.mm_modem_signal_interface = MMModemSignalInterface(self.modem_name, self.ofono_interfaces, self.ofono_interface_props, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_signal_interface)
        await self.mm_modem_signal_interface.set_props()

    async def init_mm_location_interface(self):
        ofono2mm_print("Initialize Location interface", self.verbose)

        self.mm_modem_location_interface = MMModemLocationInterface(self.modem_name, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_location_interface)

    async def init_mm_voice_interface(self):
        ofono2mm_print("Initialize Voice interface", self.verbose)

        self.mm_modem_voice_interface = MMModemVoiceInterface(self.bus, self.ofono_client, self.modem_name, self.ofono_interfaces, self.ofono_interface_props, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_voice_interface)

        self.loop.create_task(self.init_voice_call_manager())

    async def init_mm_messaging_interface(self):
        ofono2mm_print("Initialize Messaging interface", self.verbose)

        self.mm_modem_messaging_interface = MMModemMessagingInterface(self.bus, self.modem_name, self.ofono_interfaces, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_messaging_interface)

        self.loop.create_task(self.init_message_manager())

    async def init_mm_cell_broadcast_interface(self):
        ofono2mm_print("Initialize Cell Broadcast interface", self.verbose)

        self.mm_modem_cell_broadcast_interface = MMModemCellBroadcastInterface(self.bus, self.modem_name, self.ofono_interfaces, self.verbose)
        self.bus.export(f'/org/freedesktop/ModemManager1/Modem/{self.index}', self.mm_modem_cell_broadcast_interface)

        self.loop.create_task(self.init_cell_broadcast())

    def unexport_mm_interface_objects(self):
        self.mm_sim_interface = None
        self.mm_modem3gpp_interface = None
        self.mm_modem3gpp_ussd_interface = None
        self.mm_modem3gpp_profile_manager_interface = None
        self.mm_modem_simple_interface = None
        self.mm_modem_firmware_interface = None
        self.mm_modem_time_interface = None
        self.mm_modem_cdma_interface = None
        self.mm_modem_sar_interface = None
        self.mm_modem_oma_interface = None
        self.mm_modem_signal_interface = None
        self.mm_modem_location_interface = None
        self.mm_modem_voice_interface = None
        self.mm_modem_messaging_interface = None
        self.mm_modem_cell_broadcast_interface = None

        for object in self.mm_interface_objects:
            try:
                ofono2mm_print(f"Unexporting object at path {object}", self.verbose)
                self.bus.unexport(object)
            except Exception as e:
                ofono2mm_print(f"Failed to unexport object at path {object}: {e}", self.verbose)

        for bearer_interface in self.mm_bearer_interfaces:
            bearer_interface = None

        try:
            self.bus.unexport(f'/org/freedesktop/ModemManager1/Modem/{self.index}')
        except Exception as e:
            ofono2mm_print(f"Failed to unexport object at path /org/freedesktop/ModemManager1/Modem/{self.index}: {e}", self.verbose)

    def get_mm_modem_simple_interface(self):
        return self.mm_modem_simple_interface

    async def check_ofono_contexts(self):
        ofono2mm_print("Checking ofono contexts", self.verbose)

        if 'org.ofono.SimManager' in self.ofono_interface_props and 'Present' in self.ofono_interface_props['org.ofono.SimManager'].props:
            if not self.ofono_interface_props['org.ofono.SimManager']['Present'].value:
                ofono2mm_print("SIM is not present. no need to check ofono contexts", self.verbose)
                return
        else:
            ofono2mm_print("SIM manager is not up yet. cannot check ofono contexts", self.verbose)
            return

        if not (not 'PinRequired' in self.ofono_interface_props['org.ofono.SimManager'].props or self.ofono_interface_props['org.ofono.SimManager']['PinRequired'].value == 'none'):
            ofono2mm_print("SIM is still locked and/or not ready. cannot check ofono contexts", self.verbose)
            return

        global bearer_i

        # ConnectionManager and get_contexts can take a bit to come up, so...

        retries_left = 5

        while retries_left > 0:
            try:
                contexts = await self.ofono_proxy['org.ofono.ConnectionManager'].call_get_contexts()
                break
            except Exception as e:
                retries_left -= 1
                if retries_left > 0:
                    await self.add_ofono_interface('org.ofono.ConnectionManager')
                    await asyncio.sleep(0.5)
                else:
                    ofono2mm_print(f"Failed to get contexts: {e}", self.verbose)
                    return

        old_bearer_list = self.props['Bearers'].value
        for ctx in contexts:
            if ctx[1]['Type'].value == "internet":
                mm_bearer_interface = MMBearerInterface(self.ofono_client, self.modem_name, self.ofono_interfaces, self, self.verbose)
                self.mm_bearer_interfaces.append(mm_bearer_interface)

                ipv4_method = 0
                ipv4_address = ''
                ipv4_dns = []
                ipv4_gateway = ''

                if 'Settings' in ctx[1] and ctx[1]['Settings'].value:
                    settings = ctx[1]['Settings'].value
                    if 'Method' in settings:
                        if settings['Method'].value == "static":
                            ipv4_method = 2
                        elif settings['Method'].value == "dhcp":
                            ipv4_method = 3

                    if 'Address' in settings:
                        ipv4_address = settings['Address'].value

                    if 'DomainNameServers' in settings:
                        for dns in settings['DomainNameServers'].value:
                            ipv4_dns.append(dns)

                    if 'Gateway' in settings:
                        ipv4_gateway = settings['Gateway'].value

                ipv6_method = 0
                ipv6_address = ''
                ipv6_dns = []
                ipv6_gateway = ''

                if 'IPv6.Settings' in ctx[1] and ctx[1]['IPv6.Settings'].value:
                    ipv6_settings = ctx[1]['IPv6.Settings'].value

                    if 'Address' in ipv6_settings and ipv6_settings['Address'].value:
                        ipv6_method = 2  # static
                        ipv6_address = ipv6_settings['Address'].value

                    if 'DomainNameServers' in ipv6_settings:
                        for dns in ipv6_settings['DomainNameServers'].value:
                            ipv6_dns.append(dns)

                    if 'Gateway' in ipv6_settings:
                        ipv6_gateway = ipv6_settings['Gateway'].value

                mm_bearer_interface.props.update({
                    "Interface": ctx[1]['Settings'].value.get("Interface", Variant('s', '')) if 'Settings' in ctx[1] else Variant('s', ''),
                    "Connected": ctx[1]['Active'],
                    "Ip4Config": Variant('a{sv}', {
                        "method": Variant('u', ipv4_method),
                        "address": Variant('s', ipv4_address),
                        "dns1": Variant('s', ipv4_dns[0] if len(ipv4_dns) > 0 else ''),
                        "dns2": Variant('s', ipv4_dns[1] if len(ipv4_dns) > 1 else ''),
                        "dns3": Variant('s', ipv4_dns[2] if len(ipv4_dns) > 2 else ''),
                        "gateway": Variant('s', ipv4_gateway)
                    }),
                    "Ip6Config": Variant('a{sv}', {
                        "method": Variant('u', ipv6_method),
                        "address": Variant('s', ipv6_address),
                        "dns1": Variant('s', ipv6_dns[0] if len(ipv6_dns) > 0 else ''),
                        "dns2": Variant('s', ipv6_dns[1] if len(ipv6_dns) > 1 else ''),
                        "dns3": Variant('s', ipv6_dns[2] if len(ipv6_dns) > 2 else ''),
                        "gateway": Variant('s', ipv6_gateway)
                    }),
                    "Properties": Variant('a{sv}', {
                        "apn": ctx[1]['AccessPointName']
                    })
                })

                if 'Settings' in ctx[1] and 'Interface' in ctx[1]['Settings'].value:
                    self.props['Ports'].value.append([ctx[1]['Settings'].value['Interface'].value, 2]) # port type AT MM_MODEM_PORT_TYPE_AT
                    self.emit_properties_changed({'Ports': self.props['Ports'].value})

                ofono_ctx_interface = self.ofono_client["ofono_context"][ctx[0]]["org.ofono.ConnectionContext"]
                ofono_ctx_interface.on_property_changed(mm_bearer_interface.ofono_context_changed)
                mm_bearer_interface.ofono_ctx = ctx[0]

                object_path = f'/org/freedesktop/ModemManager/Bearer/{bearer_i}'
                mm_bearer_interface.own_object_path = object_path
                self.bus.export(object_path, mm_bearer_interface)
                self.props['Bearers'].value.append(object_path)
                self.bearers[object_path] = mm_bearer_interface

                if object_path not in self.mm_interface_objects:
                    self.mm_interface_objects.append(object_path)

                bearer_i += 1

        if self.props['Bearers'].value != old_bearer_list:
            self.emit_properties_changed({'Bearers': self.props['Bearers'].value})

        self.ofono_interfaces['org.ofono.ConnectionManager'].on_context_added(self.ofono_context_added)

    def ofono_context_added(self, path, properties):
        ofono2mm_print(f"oFono context added with path {path} and properties {properties}", self.verbose)

        global bearer_i
        if properties['Type'] == "internet":
            mm_bearer_interface = MMBearerInterface(self.ofono_client, self.modem_name, self.ofono_interfaces, self, self.verbose)
            self.mm_bearer_interfaces.append(mm_bearer_interface)

            ipv4_method = 0
            ipv4_address = ''
            ipv4_dns = []
            ipv4_gateway = ''

            if 'Settings' in properties and properties['Settings'].value:
                settings = properties['Settings'].value
                if 'Method' in settings:
                    if settings['Method'].value == "static":
                        ipv4_method = 2
                    elif settings['Method'].value == "dhcp":
                        ipv4_method = 3

                if 'Address' in settings:
                    ipv4_address = settings['Address'].value

                if 'DomainNameServers' in settings:
                    for dns in settings['DomainNameServers'].value:
                        ipv4_dns.append(dns)

                if 'Gateway' in settings:
                    ipv4_gateway = settings['Gateway'].value

            ipv6_method = 0
            ipv6_address = ''
            ipv6_dns = []
            ipv6_gateway = ''

            if 'IPv6.Settings' in properties and properties['IPv6.Settings'].value:
                ipv6_settings = properties['IPv6.Settings'].value

                if 'Address' in ipv6_settings and ipv6_settings['Address'].value:
                    ipv6_method = 2  # static
                    ipv6_address = ipv6_settings['Address'].value

                if 'DomainNameServers' in ipv6_settings:
                    for dns in ipv6_settings['DomainNameServers'].value:
                        ipv6_dns.append(dns)

                if 'Gateway' in ipv6_settings:
                    ipv6_gateway = ipv6_settings['Gateway'].value

            mm_bearer_interface.props.update({
                "Interface": properties['Settings'].value.get('Interface', Variant('s', '')) if 'Settings' in properties else Variant('s', ''),
                "Connected": properties['Active'],
                "Ip4Config": Variant('a{sv}', {
                    "method": Variant('u', ipv4_method),
                    "address": Variant('s', ipv4_address),
                    "dns1": Variant('s', ipv4_dns[0] if len(ipv4_dns) > 0 else ''),
                    "dns2": Variant('s', ipv4_dns[1] if len(ipv4_dns) > 1 else ''),
                    "dns3": Variant('s', ipv4_dns[2] if len(ipv4_dns) > 2 else ''),
                    "gateway": Variant('s', ipv4_gateway)
                }),
                "Ip6Config": Variant('a{sv}', {
                    "method": Variant('u', ipv6_method),
                    "address": Variant('s', ipv6_address),
                    "dns1": Variant('s', ipv6_dns[0] if len(ipv6_dns) > 0 else ''),
                    "dns2": Variant('s', ipv6_dns[1] if len(ipv6_dns) > 1 else ''),
                    "dns3": Variant('s', ipv6_dns[2] if len(ipv6_dns) > 2 else ''),
                    "gateway": Variant('s', ipv6_gateway)
                }),
                "Properties": Variant('a{sv}', {
                    "apn": properties['AccessPointName']
                })
            })

            if 'Settings' in properties and 'Interface' in properties['Settings'].value:
                self.props['Ports'].value.append([properties['Settings'].value['Interface'].value, 2])
                self.emit_properties_changed({'Ports': self.props['Ports'].value})

            ofono_ctx_interface = self.ofono_client["ofono_context"][path]['org.ofono.ConnectionContext']
            ofono_ctx_interface.on_property_changed(mm_bearer_interface.ofono_context_changed)
            mm_bearer_interface.ofono_ctx = path

            object_path = f'/org/freedesktop/ModemManager/Bearer/{bearer_i}'
            mm_bearer_interface.own_object_path = object_path
            self.bus.export(object_path, mm_bearer_interface)
            self.props['Bearers'].value.append(object_path)
            self.bearers[object_path] = mm_bearer_interface

            if object_path not in self.mm_interface_objects:
                self.mm_interface_objects.append(object_path)

            bearer_i += 1
            self.emit_properties_changed({'Bearers': self.props['Bearers'].value})

    async def sim_unlocked(self):
        ofono2mm_print("SIM is now unlocked, exporting all interfaces again", self.verbose)

        self.loop.create_task(self.init_connection_manager())

        promises = []
        for iface in self.used_interfaces:
            promises.append(self.add_ofono_interface(iface))

        await asyncio.gather(*promises)

        await self.release_request_modemmanager()

    async def release_request_modemmanager(self):
        ofono2mm_print("Releasing and requesting the bus name", self.verbose)

        if hasattr(self, '_releasing'):
            ofono2mm_print("Failed to release and request, operation already in progress", self.verbose)
            return
        self._releasing = True

        # Release and request the name so other apps realize we're here.
        # TODO: this feels like it shouldn't be necessary. We are signaling InterfacesAdded, so... why?

        try:
            await self.bus.release_name('org.freedesktop.ModemManager1')
        except Exception as e:
            ofono2mm_print(f"Failed to release name: {e}", self.verbose)

        try:
            await self.bus.request_name('org.freedesktop.ModemManager1')
        except Exception as e:
            ofono2mm_print(f"Failed to request name: {e}", self.verbose)

        delattr(self, '_releasing')

    async def set_props(self):
        ofono2mm_print("Setting properties", self.verbose)

        old_props = deepcopy(self.props)

        old_state = self.props['State'].value
        self.props['UnlockRequired'] = Variant('u', 1) # modem is unlocked MM_MODEM_LOCK_NONE
        if 'Powered' in self.ofono_interface_props['org.ofono.Modem'].props and self.ofono_interface_props['org.ofono.Modem']['Powered'].value and 'org.ofono.SimManager' in self.ofono_interface_props and self.enabled:
            if 'Present' in self.ofono_interface_props['org.ofono.SimManager'].props:
                if not self.was_powered:
                    # Bring the modem online now that it's powered
                    try:
                        await self.ofono_proxy['org.ofono.Modem'].call_set_property('Online', Variant('b', True))
                        self.was_powered = True
                        await self.release_request_modemmanager()
                    except Exception as e:
                        # Might happen in airplane mode although powered should be false. Just coverin' our bases.
                        ofono2mm_print(f"Failed to set Online to True: {e}", self.verbose)
                        pass

                if self.ofono_interface_props['org.ofono.SimManager']['Present'].value:
                    if not 'PinRequired' in self.ofono_interface_props['org.ofono.SimManager'].props or self.ofono_interface_props['org.ofono.SimManager']['PinRequired'].value == 'none':
                        self.props['UnlockRequired'] = Variant('u', 1) # modem is unlocked MM_MODEM_LOCK_NONE
                        if self.ofono_interface_props['org.ofono.Modem']['Online'].value:
                            if 'org.ofono.NetworkRegistration' in self.ofono_interface_props:
                                if ("Status" in self.ofono_interface_props['org.ofono.NetworkRegistration'].props):
                                    if self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == 'registered' or self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == 'roaming':
                                        self.props['State'] = Variant('i', 8) # modem is registered MM_MODEM_STATE_REGISTERED
                                        if 'Strength' in self.ofono_interface_props['org.ofono.NetworkRegistration'].props:
                                            self.props['SignalQuality'] = Variant('(ub)', [self.ofono_interface_props['org.ofono.NetworkRegistration']['Strength'].value, True])
                                    elif self.ofono_interface_props['org.ofono.NetworkRegistration']['Status'].value == 'searching':
                                        self.props['State'] = Variant('i', 7) # modem is searching MM_MODEM_STATE_SEARCHING
                                    else:
                                        self.props['State'] = Variant('i', 6) # modem is enabled MM_MODEM_STATE_ENABLED
                                else:
                                    self.props['State'] = Variant('i', 6) # modem is enabled MM_MODEM_STATE_ENABLED
                            else:
                                self.props['State'] = Variant('i', 6) # modem is enabled MM_MODEM_STATE_ENABLED
                        else:
                            self.props['State'] = Variant('i', 3) # modem is disabled MM_MODEM_STATE_DISABLED

                        self.props['UnlockRequired'] = Variant('u', 1) # modem is unlocked MM_MODEM_LOCK_NONE
                    else:
                        self.props['UnlockRequired'] = Variant('u', 2) # modem needs a pin MM_MODEM_LOCK_SIM_PIN
                        self.props['State'] = Variant('i', 2) # modem is locked MM_MODEM_STATE_LOCKED
                        self.locked = True

                    self.props['Sim'] = self.sim
                    self.props['StateFailedReason'] = Variant('i', 0) # no failure MM_MODEM_STATE_FAILED_REASON_NONE
                else:
                    self.props['Sim'] = Variant('o', '/')
                    self.props['State'] = Variant('i', -1) # state unknown
                    self.props['StateFailedReason'] = Variant('i', 2) # sim missing MM_MODEM_STATE_FAILED_REASON_SIM_MISSING
            else:
                self.props['State'] = Variant('i', -1) # state unknown
                self.props['StateFailedReason'] = Variant('i', 2) # sim missing MM_MODEM_STATE_FAILED_REASON_SIM_MISSING

            self.props['PowerState'] = Variant('i', 3) # power is on MM_MODEM_POWER_STATE_ON

            lock_state = self.props['UnlockRequired'].value > 1
            if self.locked == True and self.locked != lock_state:
                self.locked = False
                await self.sim_unlocked()
        else:
            self.was_powered = False
            self.props['State'] = Variant('i', 3) # modem is disabled MM_MODEM_STATE_DISABLED
            self.props['PowerState'] = Variant('i', 1) # power is off MM_MODEM_POWER_STATE_OFF

        if 'org.ofono.SimManager' in self.ofono_interface_props:
            self.props['OwnNumbers'] = Variant('as', self.ofono_interface_props['org.ofono.SimManager']['SubscriberNumbers'].value if 'SubscriberNumbers' in self.ofono_interface_props['org.ofono.SimManager'].props else [])

            if 'Retries' in self.ofono_interface_props['org.ofono.SimManager'].props:
                unlock_retries = {}
                if 'pin' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[2] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['pin'] # MM_MODEM_LOCK_SIM_PIN

                if 'pin2' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[3] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['pin2'] # MM_MODEM_LOCK_SIM_PIN2

                if 'puk' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[4] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['puk'] # MM_MODEM_LOCK_SIM_PUK

                if 'puk2' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[5] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['puk2'] # MM_MODEM_LOCK_SIM_PUK2

                if 'service' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[6] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['service'] # MM_MODEM_LOCK_PH_SP_PIN

                if 'servicepuk' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[7] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['servicepuk'] # MM_MODEM_LOCK_PH_SP_PUK

                if 'network' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[8] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['network'] # MM_MODEM_LOCK_PH_NET_PIN

                if 'networkpuk' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[9] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['networkpuk'] # MM_MODEM_LOCK_PH_NET_PUK

                if 'corp' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[11] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['corp'] # MM_MODEM_LOCK_PH_CORP_PIN

                if 'corppuk' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[12] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['corppuk'] # MM_MODEM_LOCK_PH_CORP_PUK

                if 'netsub' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[15] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['netsub'] # MM_MODEM_LOCK_PH_NETSUB_PIN

                if 'netsubpuk' in self.ofono_interface_props['org.ofono.SimManager']['Retries'].value:
                    unlock_retries[16] = self.ofono_interface_props['org.ofono.SimManager']['Retries'].value['netsubpuk'] # MM_MODEM_LOCK_PH_NETSUB_PUK
            else:
                unlock_retries = {}

            self.props['UnlockRetries'] = Variant('a{uu}', unlock_retries)
        else:
            self.props['OwnNumbers'] = Variant('as', [])
            self.props['UnlockRetries'] = Variant('a{uu}', {})

        if 'org.ofono.NetworkRegistration' in self.ofono_interface_props and self.props['State'].value == 8:
            if "Technology" in self.ofono_interface_props['org.ofono.NetworkRegistration']:
                current_tech = 0
                if self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "nr":
                    current_tech |= 1 << 15 # network is 5g MM_MODEM_ACCESS_TECHNOLOGY_5GNR
                    self.mm_cell_type = 6 # cell type is 5g MM_CELL_TYPE_5GNR
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "lte":
                    current_tech |= 1 << 14 # network is lte MM_MODEM_ACCESS_TECHNOLOGY_LTE
                    self.mm_cell_type = 5 # cell type is lte MM_CELL_TYPE_LTE
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "hspap":
                    current_tech |= 1 << 9 # network is hspa plus MM_MODEM_ACCESS_TECHNOLOGY_HSPA_PLUS
                    self.mm_cell_type = 3 # cell type is umts MM_CELL_TYPE_UMTS
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "hspa":
                    current_tech |= 1 << 8 # network is hspa MM_MODEM_ACCESS_TECHNOLOGY_HSPA
                    self.mm_cell_type = 3 # cell type is umts MM_CELL_TYPE_UMTS
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "hsupa":
                    current_tech |= 1 << 7 # network is hsupa MM_MODEM_ACCESS_TECHNOLOGY_HSUPA
                    self.mm_cell_type = 3 # cell type is umts MM_CELL_TYPE_UMTS
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "hsdpa":
                    current_tech |= 1 << 6 # network is hsdpa MM_MODEM_ACCESS_TECHNOLOGY_HSDPA
                    self.mm_cell_type = 3 # cell type is umts MM_CELL_TYPE_UMTS
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "umts":
                    current_tech |= 1 << 5 # network is umts MM_MODEM_ACCESS_TECHNOLOGY_UMTS
                    self.mm_cell_type = 3 # cell type is umts MM_CELL_TYPE_UMTS
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "edge":
                    current_tech |= 1 << 4 # network is edge MM_MODEM_ACCESS_TECHNOLOGY_EDGE
                    self.mm_cell_type = 2 # cell type is gsm MM_CELL_TYPE_GSM
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "gprs":
                    current_tech |= 1 << 3 # network is gprs MM_MODEM_ACCESS_TECHNOLOGY_GPRS
                    self.mm_cell_type = 2 # cell type is gsm MM_CELL_TYPE_GSM
                elif self.ofono_interface_props['org.ofono.NetworkRegistration']["Technology"].value == "gsm":
                    current_tech |= 1 << 1 # network is gsm MM_MODEM_ACCESS_TECHNOLOGY_GSM
                    self.mm_cell_type = 2 # cell type is gsm MM_CELL_TYPE_GSM

                self.props['AccessTechnologies'] = Variant('u', current_tech)
            else:
                self.props['AccessTechnologies'] = Variant('u', 0) # network is unknown MM_MODEM_ACCESS_TECHNOLOGY_UNKNOWN
        else:
            self.props['AccessTechnologies'] = Variant('u', 0)
            self.props['SignalQuality'] = Variant('(ub)', [0, False])

        caps = 0
        modes = 0
        pref = 0
        supported_bands = []
        gsm_bands = [1, 2, 3, 4, 14, 15, 16, 17, 18, 19, 20]
        umts_bands = [5, 6, 7, 8, 9, 10, 11, 12, 13, 210, 211, 212, 213, 214, 219, 220, 221, 222, 225, 226, 232]
        lte_bands = [31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 115]
        nr_bands = [301, 302, 303, 305, 307, 308, 312, 313, 314, 318, 320, 325, 326, 328, 329, 330, 334, 338, 339, 340, 341, 348, 350, 351, 353, 365, 366, 370, 371, 374, 375, 376, 377, 378, 379, 380, 381, 382, 383, 384, 386, 389, 390, 391, 392, 393, 394, 395, 557, 558, 560, 561]
        if 'org.ofono.RadioSettings' in self.ofono_interface_props:
            if 'AvailableTechnologies' in self.ofono_interface_props['org.ofono.RadioSettings'].props:
                ofono_techs = self.ofono_interface_props['org.ofono.RadioSettings']['AvailableTechnologies'].value
                if 'gsm' in ofono_techs:
                    caps |= 4
                    modes |= 2
                    supported_bands.extend(gsm_bands)
                if 'umts' in ofono_techs:
                    caps |= 4
                    modes |= 4
                    supported_bands.extend(umts_bands)
                if 'lte' in ofono_techs:
                    caps |= 8
                    modes |= 8
                    supported_bands.extend(lte_bands)
                if 'nr' in ofono_techs:
                    caps |= 16
                    modes |= 16
                    supported_bands.extend(nr_bands)

            if 'TechnologyPreference' in self.ofono_interface_props['org.ofono.RadioSettings'].props:
                ofono_pref =  self.ofono_interface_props['org.ofono.RadioSettings']['TechnologyPreference'].value
                if ofono_pref == 'nr':
                    pref = 16 # current mode nr MM_MODEM_MODE_5G
                if ofono_pref == 'lte':
                    pref = 8 # current mode lte MM_MODEM_MODE_4G
                if ofono_pref == 'umts':
                    pref = 4 # current mode umts MM_MODEM_MODE_3G
                if ofono_pref == 'gsm':
                    pref = 2 # current mode gsm MM_MODEM_MODE_2G

        self.props['CurrentCapabilities'] = Variant('u', caps)
        self.props['SupportedCapabilities'] = Variant('au', [caps])

        self.props['CurrentBands'] = Variant('au', supported_bands)
        self.props['SupportedBands'] = Variant('au', supported_bands)

        if caps == 0:
            self.props['CurrentCapabilities'] = Variant('u', 4) # lte MM_MODEM_CAPABILITY_LTE
            self.props['SupportedCapabilities'] = Variant('au', [4]) # lte MM_MODEM_CAPABILITY_LTE

        supported_modes = []
        if modes == 30: # gsm umts lte nr
            supported_modes.append([30, 16]) # nr
            supported_modes.append([30, 8]) # lte
            supported_modes.append([30, 4]) # umts
            supported_modes.append([30, 2]) # gsm
            supported_modes.append([14, 8]) # lte
            supported_modes.append([14, 4]) # umts
            supported_modes.append([14, 2]) # gsm
            supported_modes.append([12, 8]) # lte
            supported_modes.append([12, 4]) # umts
            supported_modes.append([10, 8]) # lte
            supported_modes.append([10, 2]) # gsm
            supported_modes.append([6, 4]) # umts
            supported_modes.append([6, 2]) # gsm
            supported_modes.append([8, 0]) # none
            supported_modes.append([4, 0]) # none
            supported_modes.append([2, 0]) # none
        if modes == 14: # gsm umts lte
            supported_modes.append([14, 8]) # lte
            supported_modes.append([14, 4]) # umts
            supported_modes.append([14, 2]) # gsm
            supported_modes.append([12, 8]) # lte
            supported_modes.append([12, 4]) # umts
            supported_modes.append([10, 8]) # lte
            supported_modes.append([10, 2]) # gsm
            supported_modes.append([6, 4]) # umts
            supported_modes.append([6, 2]) # gsm
            supported_modes.append([8, 0]) # none
            supported_modes.append([4, 0]) # none
            supported_modes.append([2, 0]) # none
        if modes == 6: # gsm umts
            supported_modes.append([6, 4]) # umts
            supported_modes.append([2, 0]) # none
        if modes == 2: # gsm
            supported_modes.append([2, 0]) # none

        self.props['SupportedModes'] = Variant('a(uu)', supported_modes)
        if self.selected_current_mode in supported_modes:
            self.props['CurrentModes'] = Variant('(uu)', self.selected_current_mode)
        elif read_setting("current_mode") != "False":
            self.selected_current_mode = literal_eval(read_setting("current_mode").strip())
            if self.selected_current_mode in supported_modes:
                self.props['CurrentModes'] = Variant('(uu)', self.selected_current_mode)
            else:
                self.props['CurrentModes'] = Variant('(uu)', [8, 0])
        else:
            self.props['CurrentModes'] = Variant('(uu)', [8, 0]) # allowed 4g, preferred none

        if supported_modes == []:
            self.props['SupportedModes'] = Variant('a(uu)', [[0, 0]]) # allowed mode none, preferred mode none MM_MODEM_MODE_NONE
            self.props['CurrentModes'] = Variant('(uu)', [0, 0]) # allowed mode none, preferred mode none MM_MODEM_MODE_NONE

        self.props['EquipmentIdentifier'] = Variant('s', self.ofono_interface_props['org.ofono.Modem']['Serial'].value if 'Serial' in self.ofono_interface_props['org.ofono.Modem'].props else '')
        self.props['HardwareRevision'] = Variant('s', self.ofono_interface_props['org.ofono.Modem']['Revision'].value if 'Revision' in self.ofono_interface_props['org.ofono.Modem'].props else '')
        self.props['Revision'] = Variant('s', self.ofono_interface_props['org.ofono.Modem']['SoftwareVersionNumber'].value if 'SoftwareVersionNumber' in self.ofono_interface_props['org.ofono.Modem'].props else '')
        self.props['Manufacturer'] = Variant('s', self.ofono_interface_props['org.ofono.Modem']['Manufacturer'].value if 'Manufacturer' in self.ofono_interface_props['org.ofono.Modem'].props else 'ofono')
        self.props['Model'] = Variant('s', self.ofono_interface_props['org.ofono.Modem']['Model'].value if 'Model' in self.ofono_interface_props['org.ofono.Modem'].props else 'binder')

        if old_state != self.props['State'].value:
            self.StateChanged(old_state, self.props['State'].value, 0)

        changed_props = {}
        for prop in self.props:
            if self.props[prop].value != old_props[prop].value:
                changed_props.update({ prop: self.props[prop].value })

        if changed_props:
            self.emit_properties_changed(changed_props)

    @method()
    async def Enable(self, enable: 'b'):
        ofono2mm_print(f"Enable with state {enable}", self.verbose)

        if self.props['State'].value == -1:
            ofono2mm_print("Modem is in an unknown state, skipping", self.verbose)
            return

        self.enabled = enable

        if enable:
            try:
                await self.ofono_modem.call_set_property('Powered', Variant('b', enable))
                await self.ofono_modem.call_set_property('Online', Variant('b', enable))
            except Exception as e:
                ofono2mm_print(f"Failed to enable with state {enable}: {e}", self.verbose)
        else:
            try:
                await self.ofono_modem.call_set_property('Online', Variant('b', enable))
            except Exception as e:
                ofono2mm_print(f"Failed to enable with state {enable}: {e}", self.verbose)

        old_state = self.props['State'].value
        self.props['State'] = Variant('i', 6 if enable else 3) # 6 is STATE_ENABLED, 3 is STATE_DISABLED
        self.StateChanged(old_state, self.props['State'].value, 0)
        self.emit_properties_changed({'State': self.props['State'].value})

        await self.set_props()

    @method()
    def ListBearers(self) -> 'ao':
        ofono2mm_print("Listing bearers", self.verbose)
        return self.props['Bearers'].value

    @method()
    async def CreateBearer(self, properties: 'a{sv}') -> 'o':
        ofono2mm_print(f"Create bearer with properties {properties}", self.verbose)

        try:
            return await self.doCreateBearer(properties)
        except Exception as e:
            ofono2mm_print(f"Failed to create bearer with properties {properties}: {e}", self.verbose)

    async def doCreateBearer(self, properties):
        global bearer_i

        # ConnectionManager and get_contexts can take a bit to come up, so...

        retries_left = 5

        while retries_left > 0:
            try:
                contexts = await self.ofono_proxy['org.ofono.ConnectionManager'].call_get_contexts()
                break
            except Exception as e:
                retries_left -= 1
                if retries_left > 0:
                    await self.add_ofono_interface('org.ofono.ConnectionManager')
                    await asyncio.sleep(0.5)
                else:
                    ofono2mm_print(f"Failed to get contexts: {e}", self.verbose)
                    return

        ofono2mm_print(f"Creating bearer {bearer_i} with properties: {properties}", self.verbose)
        mm_bearer_interface = MMBearerInterface(self.ofono_client, self.modem_name, self.ofono_interfaces, self, self.verbose)
        self.mm_bearer_interfaces.append(mm_bearer_interface)
        mm_bearer_interface.props.update({
            "Properties": Variant('a{sv}', properties)
        })

        protocol = read_setting("protocol", "ip").strip()
        ofono2mm_print(f"Creating bearer with protocol {protocol}", self.verbose)

        # users would usually have to do
        # set-context-property 0 AccessPointName example.apn && activate-context 1
        # to activate the correct context for ofono2mm to use, lets do it on bearer creation to not need ofono scripts
        chosen_apn = ''
        ofono_ctx = ''
        internet_ctx_exists = False
        contexts = []
        try:
            contexts = await self.ofono_proxy['org.ofono.ConnectionManager'].call_get_contexts()
        except Exception as e:
            ofono2mm_print(f"Failed to get ofono contexts, ignoring", self.verbose)

        for ctx in contexts:
            name = ctx[1].get('Type', Variant('s', '')).value
            apn = ctx[1].get('AccessPointName', Variant('s', '')).value
            if name.lower() == "internet":
                if apn:
                    chosen_apn = apn
                ofono_ctx = ctx[0]

            if ofono_ctx:
                internet_ctx_exists = True
                ofono_ctx_interface = self.ofono_client["ofono_context"][ofono_ctx]['org.ofono.ConnectionContext']
                await ofono_ctx_interface.call_set_property("Active", Variant('b', False))
                await ofono_ctx_interface.call_set_property("AccessPointName", Variant('s', chosen_apn))
                await ofono_ctx_interface.call_set_property("Protocol", Variant('s', protocol))
                await ofono_ctx_interface.call_set_property("Active", Variant('b', True))

        if not internet_ctx_exists:
            try:
                ofono_ctx = await self.ofono_proxy['org.ofono.ConnectionManager'].call_add_context("internet")
                ofono_ctx_interface = self.ofono_client["ofono_context"][ofono_ctx]['org.ofono.ConnectionContext']
                if 'apn' in properties:
                    await ofono_ctx_interface.call_set_property("AccessPointName", properties['apn'])
                await ofono_ctx_interface.call_set_property("Protocol", Variant('s', protocol))
                mm_bearer_interface.ofono_ctx = ofono_ctx
                await mm_bearer_interface.add_auth_ofono(properties['username'].value if 'username' in properties else '',
                                                         properties['password'].value if 'password' in properties else '')
            except Exception as e:
               # should be fine? both apndb and mbpi provision do this for us so.... lets just ignore for now
               ofono2mm_print(f"Failed to create internet context: {e}, ignoring", self.verbose)
        else:
            mm_bearer_interface.ofono_ctx = ofono_ctx
            try:
                await mm_bearer_interface.add_auth_ofono(properties['username'].value if 'username' in properties else '',
                                                         properties['password'].value if 'password' in properties else '')
            except Exception as e:
               # this should also be fine, as it again comes from apndb or mbpi so we don't really nee to touch it
               ofono2mm_print(f"Failed to set ofono authentication: {e}, ignoring", self.verbose)

        object_path = f'/org/freedesktop/ModemManager/Bearer/{bearer_i}'
        mm_bearer_interface.own_object_path = object_path
        self.bus.export(object_path, mm_bearer_interface)

        self.props['Bearers'].value.append(object_path)
        self.bearers[object_path] = mm_bearer_interface

        if object_path not in self.mm_interface_objects:
            self.mm_interface_objects.append(object_path)

        bearer_i += 1
        self.emit_properties_changed({'Bearers': self.props['Bearers'].value})

        ofono2mm_print(f"Exported bearer at object path {object_path}", self.verbose)

        return object_path

    @method()
    async def DeleteBearer(self, path: 'o'):
        ofono2mm_print(f"Delete bearer with object path {path}", self.verbose)

        if path in self.props['Bearers'].value:
            self.props['Bearers'].value.remove(path)
            await self.ofono_proxy['org.ofono.ConnectionManager'].call_remove_context(self.bearers[path].ofono_ctx)
            self.bearers.pop(path)
            self.bus.unexport(path)
            self.emit_properties_changed({'Bearers': self.props['Bearers'].value})

            if path in self.mm_interface_objects:
                self.mm_interface_objects.remove(path)
        else:
            ofono2mm_print(f"Bearer with path {path} does not exist in Bearers property: {self.props['Bearers'].value}", self.verbose)

    @method()
    async def Reset(self):
        ofono2mm_print("Resetting modem", self.verbose)

        await self.ofono_modem.call_set_property('Powered', Variant('b', False))
        await self.ofono_modem.call_set_property('Powered', Variant('b', True))

        old_state = self.props['State'].value
        self.props['State'] = Variant('i', 6)  # 6 typically represents an enabled state
        self.StateChanged(old_state, self.props['State'].value, 0)
        self.emit_properties_changed({'State': self.props['State'].value})

        await self.ofono_modem.call_set_property('Online', Variant('b', True))

        await self.set_props()

    @method()
    async def FactoryReset(self, code: 's'):
        ofono2mm_print(f"Factory Resetting modem with carrier code {code}", self.verbose)

        # not quite a factory reset but better than nothing
        await self.ofono_modem.call_set_property('Powered', Variant('b', False))
        await self.ofono_modem.call_set_property('Powered', Variant('b', True))

        old_state = self.props['State'].value
        self.props['State'] = Variant('i', 6)  # 6 typically represents an enabled state
        self.StateChanged(old_state, self.props['State'].value, 0)
        self.emit_properties_changed({'State': self.props['State'].value})

        await self.ofono_modem.call_set_property('Online', Variant('b', True))

        await self.set_props()

    @method()
    async def SetPowerState(self, state: 'u'):
        ofono2mm_print(f"Setting power state to {state}", self.verbose)

        if self.props['State'].value != 3:
            ofono2mm_print("SetPowerState ignored, modem is disabled", self.verbose)
            return

        if state == 1:
            self.was_powered = False
        elif state in [2, 3]:  # If state is 'on' or 'low'
            self.was_powered = True

        await self.ofono_modem.call_set_property('Powered', Variant('b', True))
        self.props['PowerState'] = Variant('i', state)
        self.emit_properties_changed({'PowerState': self.props['PowerState'].value})

        await self.set_props()

    @method()
    def SetCurrentCapabilities(self, capabilities: 'u'):
        ofono2mm_print(f"Setting current capabilities to {capabilities}", self.verbose)
        self.props['CurrentCapabilities'] = Variant('u', capabilities)
        self.emit_properties_changed({'CurrentCapabilities': self.props['CurrentCapabilities'].value})

    @method()
    async def SetCurrentModes(self, modes: '(uu)'):
        ofono2mm_print(f"Setting current modes to {modes}", self.verbose)

        if modes in self.props['SupportedModes'].value:
            if True:
                # Do nothing for now. This doesn't work well.
                return

            if modes[1] == 16:
                await self.ofono_proxy['org.ofono.RadioSettings'].call_set_property('TechnologyPreference', Variant('s', 'nr'))
            if modes[1] == 8:
                await self.ofono_proxy['org.ofono.RadioSettings'].call_set_property('TechnologyPreference', Variant('s', 'lte'))
            if modes[1] == 4:
                await self.ofono_proxy['org.ofono.RadioSettings'].call_set_property('TechnologyPreference', Variant('s', 'umts'))
            if modes[1] == 0:
                if modes[0] == 2:
                    await self.ofono_proxy['org.ofono.RadioSettings'].call_set_property('TechnologyPreference', Variant('s', 'gsm'))
                elif modes[0] == 4:
                    await self.ofono_proxy['org.ofono.RadioSettings'].call_set_property('TechnologyPreference', Variant('s', 'umts'))
                elif modes[0] == 8:
                    await self.ofono_proxy['org.ofono.RadioSettings'].call_set_property('TechnologyPreference', Variant('s', 'lte'))
                elif modes[0] == 16:
                    await self.ofono_proxy['org.ofono.RadioSettings'].call_set_property('TechnologyPreference', Variant('s', 'nr'))

            self.selected_current_mode = modes
            if read_setting('current_mode').strip() != str(modes):
                ofono2mm_print(f"Saving selected current mode {modes}", self.verbose)
                save_setting('current_mode', str(modes))

            self.props['CurrentModes'] = Variant('(uu)', modes)
            self.emit_properties_changed({'CurrentModes': self.props['CurrentModes'].value})
        else:
            raise DBusError('org.freedesktop.ModemManager1.Error.Core.Unsupported', f'The given combination of allowed and preferred modes is not supported')

    @method()
    async def SetCurrentBands(self, bands: 'au'):
        ofono2mm_print(f"Setting current bands to {bands}", self.verbose)
        band_bytes = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                      0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

        for band_definition in _BANDS:
            # HACK: The modem firmware absolutely does not like it when you disable
            # all 2G and 3G bands (but disabling all 4G and 5G is fine), so we'll just
            # always enable at least one 2G and 3G band.
            should_enable = band_definition[2] == 7 and band_definition[1] in [3, 7]
            # Same thing actually applies for 4G and 5G -- if we try to disable every band
            # it actually will just ignore the command and not disable any bands. So let's
            # just keep band 1 enabled on 4G and 5G.
            # 4G band 1:
            should_enable = should_enable or (band_definition[1] == 11 and band_definition[2] == 0)
            # 5G band 1:
            should_enable = should_enable or (band_definition[1] == 23 and band_definition[2] == 0)

            for band in bands:
                if band == band_definition[0]:
                    should_enable = True
                    break

            if should_enable:
                band_bytes[band_definition[1]] |= 1 << band_definition[2]

        # Turn the bytes into hex and group them in groups of 4, 4, 12, 12, bytes
        epbse_command = "AT+EPBSEH="

        epbse_command += "\""
        for i in range(0, 4):
            epbse_command += f"{band_bytes[i]:02x}"
        epbse_command += "\",\""

        for i in range(4, 8):
            epbse_command += f"{band_bytes[i]:02x}"
        epbse_command += "\",\""

        for i in range(8, 20):
            epbse_command += f"{band_bytes[i]:02x}"
        epbse_command += "\",\""

        for i in range(20, 32):
            epbse_command += f"{band_bytes[i]:02x}"
        epbse_command += "\""

        save_setting("current_bands", epbse_command)
        await self._send_at_command(epbse_command)

        # We also want to set ERAT to 22 to ensure all RATs are enabled
        await self._send_at_command("AT+ERAT=22")

    @method()
    def SetPrimarySimSlot(self, sim_slot: 'u'):
        ofono2mm_print(f"Setting primary sim slot to {sim_slot}", self.verbose)
        self.props['PrimarySimSlot'] = Variant('u', sim_slot)
        self.emit_properties_changed({'PrimarySimSlot': self.props['PrimarySimSlot'].value})

    @method()
    def GetCellInfo(self) -> 'aa{sv}':
        ofono2mm_print("Returning cell info", self.verbose)

        cell_info = {
            "cell-type": Variant("u", self.mm_cell_type),
            "serving": Variant("b", self.props['State'].value == 8), # 8 should mean its registered correctly to a network
        }

        return [cell_info]

    async def _send_at_command(self, cmd: 's'):
        data_to_write = f"{cmd}\r\n"

        try:
            received_data = await self.ofono_interfaces['org.ofono.FuriLabs.AT'].call_send_command(data_to_write)
        except Exception as e:
            ofono2mm_print(f"Failed to send AT command {data_to_write.strip()}: {str(e)}", self.verbose)
            return ''

        data = received_data.strip()
        data_print = data.replace('\n', ' ')
        if data != '':
            ofono2mm_print(f"Modem returned: {data_print}", self.verbose)
            return data
        else:
            return ''

    @method()
    async def Command(self, cmd: 's', timeout: 'u') -> 's':
        # TODO: timeout isn't enforced yet
        ofono2mm_print(f"Running command {cmd} with timeout {timeout}", self.verbose)

        if cmd == '':
            return ''

        if cmd[:2] != "AT":
            return ''

        # You may be tempted to replace this with send_at_command, but if you do so,
        # it will start failing with 'ProxyInterface' object has no attribute 'call_send_command'.
        # I believe this happens because the method gets bound to the object before the AT interface
        # is fully initialized, so it doesn't have the call_send_command method yet.
        try:
            received_data = await self.ofono_interfaces['org.ofono.FuriLabs.AT'].call_send_command(f"{cmd}\r\n")
        except Exception as e:
            return ''

        data = received_data.strip()
        data_print = data.replace('\n', ' ')
        if data != '':
            ofono2mm_print(f"Modem returned: {data_print}", self.verbose)
            return data
        else:
            return ''

    @method()
    def SetProtocol(self, protocol: 'u'):
        # This is not a standard Modem Manager method. we use this method to manage context protocol (ip/dual)
        # protocol: 1 -> ip, 2 -> dual. if none specified in the configuration file, default to 1
        ofono2mm_print(f"Setting protocol to {protocol}", self.verbose)

        if protocol == 1:
            protocol_str = "ip"
        elif protocol == 2:
            protocol_str = "dual"
        else:
            protocol_str = "ip"
            ofono2mm_print(f"Protocol value {protocol} is not valid. It must be in range (1-2). Defaulting to 1", self.verbose)

        save_setting('protocol', protocol_str)

    @signal()
    def StateChanged(self, old, new, reason) -> 'iiu':
        return [old, new, reason]

    @dbus_property(access=PropertyAccess.READ)
    def Sim(self) -> 'o':
        return self.props['Sim'].value

    @dbus_property(access=PropertyAccess.READ)
    def SimSlots(self) -> 'ao':
        return self.props['SimSlots'].value

    @dbus_property(access=PropertyAccess.READ)
    def PrimarySimSlot(self) -> 'u':
        return self.props['PrimarySimSlot'].value

    @dbus_property(access=PropertyAccess.READ)
    def Bearers(self) -> 'ao':
        return self.props['Bearers'].value

    @dbus_property(access=PropertyAccess.READ)
    def SupportedCapabilities(self) -> 'au':
        return self.props['SupportedCapabilities'].value

    @dbus_property(access=PropertyAccess.READ)
    def CurrentCapabilities(self) -> 'u':
        return self.props['CurrentCapabilities'].value

    @dbus_property(access=PropertyAccess.READ)
    def MaxBearers(self) -> 'u':
        return self.props['MaxBearers'].value

    @dbus_property(access=PropertyAccess.READ)
    def MaxActiveBearers(self) -> 'u':
        return self.props['MaxActiveBearers'].value

    @dbus_property(access=PropertyAccess.READ)
    def MaxActiveMultiplexedBearers(self) -> 'u':
        return self.props['MaxActiveMultiplexedBearers'].value

    @dbus_property(access=PropertyAccess.READ)
    def Manufacturer(self) -> 's':
        return self.props['Manufacturer'].value

    @dbus_property(access=PropertyAccess.READ)
    def Model(self) -> 's':
        return self.props['Model'].value

    @dbus_property(access=PropertyAccess.READ)
    def Revision(self) -> 's':
        return self.props['Revision'].value

    @dbus_property(access=PropertyAccess.READ)
    def HardwareRevision(self) -> 's':
        return self.props['HardwareRevision'].value

    @dbus_property(access=PropertyAccess.READ)
    def DeviceIdentifier(self) -> 's':
        return self.props['DeviceIdentifier'].value

    @dbus_property(access=PropertyAccess.READ)
    def Device(self) -> 's':
        return self.props['Device'].value

    @dbus_property(access=PropertyAccess.READ)
    def Physdev(self) -> 's':
        return self.props['Physdev'].value

    @dbus_property(access=PropertyAccess.READ)
    def Drivers(self) -> 'as':
        return self.props['Drivers'].value

    @dbus_property(access=PropertyAccess.READ)
    def Plugin(self) -> 's':
        return self.props['Plugin'].value

    @dbus_property(access=PropertyAccess.READ)
    def PrimaryPort(self) -> 's':
        return self.props['PrimaryPort'].value

    @dbus_property(access=PropertyAccess.READ)
    def Ports(self) -> 'a(su)':
        return self.props['Ports'].value

    @dbus_property(access=PropertyAccess.READ)
    def EquipmentIdentifier(self) -> 's':
        return self.props['EquipmentIdentifier'].value

    @dbus_property(access=PropertyAccess.READ)
    def UnlockRequired(self) -> 'u':
        return self.props['UnlockRequired'].value

    @dbus_property(access=PropertyAccess.READ)
    def UnlockRetries(self) -> 'a{uu}':
        return self.props['UnlockRetries'].value

    @dbus_property(access=PropertyAccess.READ)
    def State(self) -> 'i':
        return self.props['State'].value

    @dbus_property(access=PropertyAccess.READ)
    def StateFailedReason(self) -> 'u':
        return self.props['StateFailedReason'].value

    @dbus_property(access=PropertyAccess.READ)
    def AccessTechnologies(self) -> 'u':
        return self.props['AccessTechnologies'].value

    @dbus_property(access=PropertyAccess.READ)
    def SignalQuality(self) -> '(ub)':
        return self.props['SignalQuality'].value

    @dbus_property(access=PropertyAccess.READ)
    def OwnNumbers(self) -> 'as':
        return self.props['OwnNumbers'].value

    @dbus_property(access=PropertyAccess.READ)
    def PowerState(self) -> 'u':
        return self.props['PowerState'].value

    @dbus_property(access=PropertyAccess.READ)
    def SupportedModes(self) -> 'a(uu)':
        return self.props['SupportedModes'].value

    @dbus_property(access=PropertyAccess.READ)
    def CurrentModes(self) -> '(uu)':
        return self.props['CurrentModes'].value

    def _parse_epbseh(self, epbseh_output):
        # Output will look like:
        # +EPBSEH: "0000009a","00000081","080808DF000000A000000002","080800D5000001A000003000"\nOK

        # We only want everything between the first : and the \n
        # Then we only want to keep the hex bytes and return an array of them like so:
        # [0, 0, 0, 0x9a, etc]
        # One thing to keep in mind is that if one of the byte groups doesn't actually need to be represented
        # as the full thing, it will omit the leading bytes. For example:
        # We can get either this:
        # +EPBSEH: "00000080","00000080","080808DF000000A000000002","080800D5000001A000003000","000000050000000000002000"
        # Or just this:
        # +EPBSEH: "00000080","00000080","080808DF000000A000000002","080800D5","00000005"
        # Note that the fourth group is shorter in the second example, because the modem doesn't have
        # any bands that it needs to represent with the last 3 bytes. So it would be equivalent to:
        # +EPBSEH: "00000080","00000080","080808DF000000A000000002","080800D50000000000000000","00000005"
        # Also, the fifth value is completely undocumented and doesn't seem to make any sense, so we'll just ignore it.

        first_colon = epbseh_output.find(':')
        newline = epbseh_output.find('\n')

        inner_content = epbseh_output[first_colon + 1:newline].strip()

        # Split by commas to get individual quoted groups
        groups = inner_content.split(',')
        output_bytes = []

        # Expected lengths for each group in characters (each byte is 2 hex chars)
        expected_lengths = [8, 8, 24, 24]  # 4 bytes, 4 bytes, 12 bytes, 12 bytes

        # Process only the first 4 groups (or fewer if not enough groups)
        for i, group in enumerate(groups[:4]):
            # Remove quotes and whitespace
            group = group.strip().strip('"')

            # Pad with zeros on the right if shorter than expected
            if i < len(expected_lengths):
                group = group.ljust(expected_lengths[i], '0')

            # Parse hex bytes in pairs
            for j in range(0, len(group), 2):
                if j+2 <= len(group):
                    output_bytes.append(int(group[j:j+2], 16))
        return output_bytes

    @dbus_property(access=PropertyAccess.READ)
    async def SupportedBands(self) -> 'au':
        try:
            supported_bands = await self._send_at_command("AT+EPBSEH=?")
            if supported_bands:
                supported_bands = self._parse_epbseh(supported_bands)
                output = []

                for band in _BANDS:
                    byte = supported_bands[band[1]]
                    if byte & 1 << band[2]:
                        output.append(band[0])

                return output
        except Exception as e:
            ofono2mm_print("Failed to get supported bands from AT: {str(e)}, returning dummy list", self.verbose)
        return self.props['SupportedBands'].value

    @dbus_property(access=PropertyAccess.READ)
    async def CurrentBands(self) -> 'au':
        try:
            current_bands = await self._send_at_command("AT+EPBSEH?")
            if current_bands:
                current_bands = self._parse_epbseh(current_bands)
                output = []

                for band in _BANDS:
                    byte = current_bands[band[1]]
                    if byte & 1 << band[2]:
                        output.append(band[0])

                return output
        except Exception as e:
            ofono2mm_print("Failed to get current bands from AT: {str(e)}, returning dummy list", self.verbose)
        return self.props['CurrentBands'].value

    @dbus_property(access=PropertyAccess.READ)
    def SupportedIpFamilies(self) -> 'u':
        return self.props['SupportedIpFamilies'].value

    @dbus_property(access=PropertyAccess.READ)
    def Protocol(self) -> 'u':
        protocol_str = read_setting("protocol", "ip").strip()
        if protocol_str == "ip":
            protocol = 1
        elif protocol_str == "dual":
            protocol = 2
        else:
            ofono2mm_print(f"Protocol string is not dual or ip. Falling back to ip", self.verbose)
            protocol = 1
        return protocol

    async def ofono_changed(self, name, varval):
        await self.set_props()
        if self.mm_modem3gpp_interface:
            self.mm_modem3gpp_interface.ofono_changed(name, varval)
        if self.mm_sim_interface:
            self.mm_sim_interface.ofono_changed(name, varval)
        if self.mm_modem_signal_interface:
            self.mm_modem_signal_interface.ofono_changed(name, varval)
        for bearer_interface in self.mm_bearer_interfaces:
            if bearer_interface:
                bearer_interface.ofono_changed(name, varval)

    def ofono_interface_changed(self, iface):
        async def ofono_interface_property_changed(name, varval):
            ofono2mm_print(f"Property name: {name}, property value: {varval.value}", self.verbose)
            if iface in self.ofono_interface_props:
                await self.set_props()
                if self.mm_modem3gpp_interface:
                    self.mm_modem3gpp_interface.ofono_interface_changed(iface)(name, varval)
                if self.mm_sim_interface:
                    self.mm_sim_interface.ofono_interface_changed(iface)(name, varval)
                if self.mm_modem_signal_interface:
                    self.mm_modem_signal_interface.ofono_interface_changed(iface)(name, varval)
        return ofono_interface_property_changed
