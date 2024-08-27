import asyncio

from dbus_next.service import ServiceInterface, method
from dbus_next import Variant

from ofono2mm.logging import ofono2mm_print

class OfonoNetworkMonitor(ServiceInterface):
    def __init__(self, bus, modem_name, ofono_client, ofono_props, ofono_interfaces, ofono_interface_props, set_props, verbose=False):
        super().__init__("org.ofono.NetworkMonitorAgent")
        self.modem_name = modem_name
        ofono2mm_print("Initializing oFono network monitor agent interface", verbose)
        self.bus = bus
        self.verbose = verbose
        self.ofono_client = ofono_client
        self.ofono_props = ofono_props
        self.ofono_interfaces = ofono_interfaces
        self.ofono_interface_props = ofono_interface_props
        self.set_props = set_props
        self.agent_path = False
        self.registered = False

    async def RegisterAgent(self, path: 'o'):
        if self.registered:
            ofono2mm_print(f"Agent already registered at path {path}", self.verbose)
            return
        else:
            ofono2mm_print(f"Registering network monitor agent at path {path}", self.verbose)

        while True:
            try:
                await self.ofono_interfaces['org.ofono.NetworkMonitor'].call_register_agent(path, 10)
                break
            except Exception as e:
                ofono2mm_print(f"Failed to register oFono push agent: {e}", self.verbose)
            await asyncio.sleep(2)

        self.bus.export(path, self)

        self.agent_path = path
        self.registered = True
        ofono2mm_print(f"Agent Registered at path {path}", self.verbose)

    async def UnregisterAgent(self, path: 'o'):
        if not self.registered:
            ofono2mm_print(f"Agent not registered at path {path}", self.verbose)
            return

        await self.ofono_interfaces['org.ofono.NetworkMonitor'].call_unregister_agent(path)

        self.agent_path = False
        self.registered = False
        ofono2mm_print(f"Agent Unregistered at path {path}", self.verbose)

    @method()
    def ServingCellInformationChanged(self, info: 'a{sv}'):
        ofono2mm_print(f"info: {info}", self.verbose)
        self.set_props(info)

    @method()
    def Release(self):
        ofono2mm_print(f"Agent released on path {self.agent_path}", self.verbose)
        self.registered = False
        self.bus.unexport(self.agent_path)

    def ofono_changed(self, name, varval):
        self.ofono_props[name] = varval

    def ofono_client_changed(self, ofono_client):
        self.ofono_client = ofono_client

    def ofono_interface_changed(self, iface):
        def ch(name, varval):
            if iface in self.ofono_interface_props:
                self.ofono_interface_props[iface][name] = varval
        return ch
