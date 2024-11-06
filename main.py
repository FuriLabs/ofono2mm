#!/usr/bin/env python3

import asyncio
import sys
from os import environ
from argparse import ArgumentParser

from dbus_fast.aio import MessageBus
from dbus_fast.service import (ServiceInterface,
                               method, dbus_property)
from dbus_fast.constants import PropertyAccess
from dbus_fast import DBusError, BusType, Variant

from ofono2mm import MMModemInterface, Ofono, DBus
from ofono2mm.utils import async_locked, read_setting
from ofono2mm.logging import ofono2mm_print
from typing import Dict

def get_version():
    return "1.22.0"

class MMInterface(ServiceInterface):
    def __init__(self, loop, bus, verbose=False):
        super().__init__('org.freedesktop.ModemManager1')
        ofono2mm_print("Initializing Manager interface", verbose)
        self.loop = loop
        self.bus = bus
        self.verbose = verbose
        self.ofono_client: Ofono = Ofono(bus)
        self.dbus_client: DBus = DBus(bus)
        self.modems: Dict[str, MMModemInterface] = {}
        self.loop.create_task(self.check_ofono_presence())

    @dbus_property(access=PropertyAccess.READ)
    def Version(self) -> 's':
        return get_version()

    @method()
    async def ScanDevices(self):
        ofono2mm_print("Scanning devices", self.verbose)

        try:
            await self.find_ofono_modems()
        except Exception as e:
            ofono2mm_print(f"Failed to scan for devices: {e}", self.verbose)
            raise DBusError("org.freedesktop.ModemManager1.Error.Core.Failed", "Failed to scan for devices")

    async def check_ofono_presence(self):
        ofono2mm_print("Checking ofono presence", self.verbose)

        dbus_iface = self.dbus_client["dbus"]["/org/freedesktop/DBus"]["org.freedesktop.DBus"]
        dbus_iface.on_name_owner_changed(self.dbus_name_owner_changed)
        has_ofono = await dbus_iface.call_name_has_owner("org.ofono")
        if has_ofono:
            self.ofono_added()
        else:
            self.ofono_removed()

    def ofono_added(self):
        ofono2mm_print("oFono added", self.verbose)

        self.ofono_manager_interface = self.ofono_client["ofono"]["/"]["org.ofono.Manager"]
        self.ofono_manager_interface.on_modem_added(self.ofono_modem_added)
        self.ofono_manager_interface.on_modem_removed(self.ofono_modem_removed)
        self.loop.create_task(self.find_ofono_modems())

    def ofono_removed(self):
        ofono2mm_print("oFono removed", self.verbose)
        self.ofono_manager_interface = None

        for path, modem in self.modems.items():
            modem.unexport_mm_interface_objects()
        self.modems.clear()

        self.loop.create_task(self.bus.release_name('org.freedesktop.ModemManager1'))

    async def find_ofono_modems(self, retry_counter=5):
        ofono2mm_print("Finding oFono modems", self.verbose)

        self.mm_modem_objects = []
        self.mm_modem_interfaces = []

        if not self.ofono_manager_interface:
            ofono2mm_print("oFono manager interface is empty, skipping", self.verbose)
            return

        try:
            modems = await self.ofono_manager_interface.call_get_modems()
        except DBusError as e:
            ofono2mm_print(f"Failed to get modems from oFono: {e}", self.verbose)
            return

        ril_modems = [modem for modem in modems if modem[0].startswith("/ril_")]

        if not ril_modems:
            ofono2mm_print("No ril modems found", self.verbose)
            # This can happen if we try to connect too early. Give it a couple seconds and give it some more shots
            # Seriously though, that's fucking stupid.
            if retry_counter <= 0:
                ofono2mm_print("No ril modems found after retries, giving up", self.verbose)
                return

            ofono2mm_print("No ril modems found, retrying", self.verbose)
            await asyncio.sleep(2)
            await self.find_ofono_modems(retry_counter - 1)

        modems_to_export = []

        for path, props in ril_modems:
            ofono2mm_print(f"Found modem: {path}, {props}", self.verbose)
            if not props['Online'].value:
                try:
                    await self.ofono_client["ofono_modem"][path]['org.ofono.Modem'].call_set_property('Online', Variant('b', True))
                except DBusError as e:
                    # Can happen if airplane mode is on. Don't worry about it.
                    ofono2mm_print(f"Failed to set modem {path} online: {e}", self.verbose)
                    pass

                props.update(await self.ofono_client["ofono_modem"][path]['org.ofono.Modem'].call_get_properties())

            try:
                sim_manager = self.ofono_client["ofono_modem"][path]['org.ofono.SimManager']
                sim_props = await sim_manager.call_get_properties()
                sim_present = sim_props['Present'].value
            except DBusError as e:
                # Can also happen if airplane mode is on.
                ofono2mm_print(f"Failed to get SIM properties for modem {path}: {e}", self.verbose)
                sim_present = False

            # If the SIM card is present, prepend it to the list of modems to export so it gets exported first
            if sim_present:
                modems_to_export.insert(0, (path, props))
            else:
                modems_to_export.append((path, props))

        for path, props in modems_to_export:
            await self.export_new_modem(path, props)

    def dbus_name_owner_changed(self, name, old_owner, new_owner):
        if name == "org.ofono":
            ofono2mm_print(f"oFono name owner changed, name: {name}, old owner: {old_owner}, new owner: {new_owner}", self.verbose)
            if new_owner == "":
                self.ofono_removed()
            else:
                self.ofono_added()

    def ofono_modem_added(self, path, mprops):
        ofono2mm_print(f"oFono modem added at path {path} and properties {mprops}", self.verbose)

        try:
            self.loop.create_task(self.export_new_modem(path, mprops))
        except Exception as e:
            ofono2mm_print(f"Failed to create task for modem {path}: {e}", self.verbose)

    async def export_new_modem(self, path, mprops):
        if not '/ril_' in path:
            # This can happen when, for example, a phone is paired over Bluetooth -- even if the phone isn't connected!
            # TODO: there is no substantial reason to not support non-RIL modems, but we are just focusing on whatever
            # provides the best user experience for now. This could be revisited in the future.
            ofono2mm_print(f"Modem {path} is not a RIL modem, skipping", self.verbose)
            return

        ofono2mm_print(f"Processing modem {path} with properties {mprops}", self.verbose)

        if path in self.modems:
            ofono2mm_print(f"Modem {path} already exists. Not sure why we're here.", self.verbose)
            return

        index = int(path.split('_')[-1])

        mm_modem_interface = MMModemInterface(self.loop, index, self.bus, self.ofono_client, path, self.verbose)
        promises = [mm_modem_interface.init_mm_sim_interface(),
                    mm_modem_interface.init_mm_3gpp_interface(),
                    mm_modem_interface.init_mm_3gpp_ussd_interface(),
                    mm_modem_interface.init_mm_3gpp_profile_manager_interface(),
                    mm_modem_interface.init_mm_messaging_interface(),
                    mm_modem_interface.init_mm_simple_interface(),
                    mm_modem_interface.init_mm_firmware_interface(),
                    mm_modem_interface.init_mm_time_interface(),
                    mm_modem_interface.init_mm_cdma_interface(),
                    mm_modem_interface.init_mm_sar_interface(),
                    mm_modem_interface.init_mm_oma_interface(),
                    mm_modem_interface.init_mm_signal_interface(),
                    mm_modem_interface.init_mm_location_interface(),
                    mm_modem_interface.init_mm_voice_interface()]

        await asyncio.gather(*promises)


        self.modems[path] = mm_modem_interface

        mm_modem_simple = mm_modem_interface.get_mm_modem_simple_interface()
        self.loop.create_task(self.simple_set_apn(mm_modem_simple))

    async def simple_set_apn(self, mm_modem_simple):
        ofono2mm_print("Setting APN in Network Manager", self.verbose)

        while True:
            ret = await mm_modem_simple.network_manager_set_apn()
            if ret:
                return

            await asyncio.sleep(2)

    def ofono_modem_removed(self, path):
        ofono2mm_print(f"oFono modem removed at path {path}", self.verbose)

        if path in self.modems:
            self.modems[path].unexport_mm_interface_objects()
            self.modems.pop(path)

    @method()
    def SetLogging(self, level: 's'):
        ofono2mm_print(f"Set logging with level {level}", self.verbose)

    @method()
    def ReportKernelEvent(self, properties: 'a{sv}'):
        ofono2mm_print(f"Report kernel events with properties {properties}", self.verbose)

    @method()
    def InhibitDevice(self, uid: 's', inhibit: 'b'):
        ofono2mm_print(f"Inhibit device with uid {uid} set to {inhibit}", self.verbose)

def print_version():
    version = get_version()
    print(f"oFono2MM version {version}")

def custom_help(parser):
    parser.print_help()
    print("\nDBus system service to control mobile broadband modems through oFono.")

async def main():
    # Disable buffering for stdout and stderr so that logs are written immediately
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    parser = ArgumentParser(description="Run the ModemManager interface.", add_help=False)
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output.')
    parser.add_argument('-V', '--version', action='store_true', help='Print version.')
    parser.add_argument('-h', '--help', action='store_true', help='Show help.')

    args = parser.parse_args()

    if args.version:
        print_version()
        return

    if args.help:
        custom_help(parser)
        return

    if environ.get('MODEM_DEBUG', 'false').lower() == 'true':
        verbose = True
    else:
        verbose = args.verbose

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    loop = asyncio.get_running_loop()
    mm_manager_interface = MMInterface(loop, bus, verbose=verbose)
    bus.export('/org/freedesktop/ModemManager1', mm_manager_interface)
    await bus.wait_for_disconnect()

if __name__ == "__main__":
    asyncio.run(main())
